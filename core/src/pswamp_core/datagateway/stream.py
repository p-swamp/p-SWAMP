# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``DataStream``: one forward-only pass over one client's range.

It makes the client contract safe for everyone downstream: a record without a
timestamp is dropped, nothing at or past the range's end is yielded, every
record passes through the gateway's enrichers, and closing the stream closes
the client's iterator. A seek is a new stream.
Adapted from Louis Pauchet's test_pswamp draft.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING

from ..log import get_logger

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

    from .data_client import DataClient
    from ..enrich import Enricher
    from ..time_range import TimeRange

__all__ = ["DataStream"]

logger = get_logger("pswamp_core.datagateway.stream")


class DataStream:
    """Async iterator over one client's records in ``time_range``."""

    def __init__(self, client: DataClient, time_range: TimeRange, enrichers: Sequence[Enricher] = ()) -> None:
        self.client = client
        self.time_range = time_range
        self.enrichers = tuple(enrichers)
        self._iterator: AsyncIterator[DataModel] | None = None

    def __aiter__(self) -> DataStream:
        return self

    async def __anext__(self) -> DataModel:
        if self._iterator is None:
            self._iterator = self._iterate()
        return await self._iterator.__anext__()

    async def aclose(self) -> None:
        """Stop, and release the client's iterator."""
        iterator, self._iterator = self._iterator, None
        if iterator is not None:
            await iterator.aclose()  # type: ignore[attr-defined]

    async def _iterate(self) -> AsyncIterator[DataModel]:
        records = self.client.consume(self.time_range)
        end = self.time_range.end
        try:
            async for record in records:
                if record.timestamp is None:
                    logger.warning("dropping a record without a timestamp from %s", self.client.name)
                    continue
                if end is not None and record.timestamp >= end:
                    return
                for enricher in self.enrichers:
                    record = enricher.enrich(record)
                yield record
        finally:
            closer = getattr(records, "aclose", None)
            if closer is not None:
                await closer()
