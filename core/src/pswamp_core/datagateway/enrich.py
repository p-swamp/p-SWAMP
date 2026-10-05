# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Enrichment: what the gateway adds to a record between provider and pipeline.

An ``Enricher`` is the gateway's hook for data no provider holds. Every record
a gateway's stream yields passes through its enrichers, so every reader (the
player, a module reading a range) sees the same enriched record. ``enrich``
runs once per record on the event loop: no I/O there.

``CimReferenceEnricher`` is the stub for the CIM reference. It sets
``PmuHeader.cimReferenceId``, an id for the grid (CIM) data that applies to a
frame; any module later in the pipeline reads it off the frame, in this process
or another. The id is decided once per layout, in ``reference_for``. The stub
returns one configured id; a lookup against a CIM model overrides that method
and nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..messages.pmu import PmuFrame

if TYPE_CHECKING:
    from ..messages.data_model import DataModel
    from ..messages.pmu import PmuHeader

__all__ = ["CimReferenceEnricher", "Enricher"]


class Enricher(ABC):
    @abstractmethod
    def enrich(self, record: DataModel) -> DataModel:
        """The record, enriched or unchanged."""


class CimReferenceEnricher(Enricher):
    """Sets ``cimReferenceId`` on each ``PmuFrame``'s header.

    Frames with one layout share one enriched header, so per frame this is a
    lookup and a shallow copy. A frame that already has a reference, or a
    layout ``reference_for`` answers ``None`` for, passes unchanged.
    """

    def __init__(self, reference: str | None) -> None:
        self.reference = reference
        self._headers: dict[str, PmuHeader | None] = {}

    def reference_for(self, header: PmuHeader) -> str | None:
        """The CIM reference for this layout. The stub: the configured one."""
        return self.reference

    def enrich(self, record: DataModel) -> DataModel:
        if not isinstance(record, PmuFrame) or record.header.cimReferenceId is not None:
            return record
        layout = record.header.header_id
        if layout not in self._headers:
            reference = self.reference_for(record.header)
            self._headers[layout] = (
                None if reference is None else record.header.model_copy(update={"cimReferenceId": reference})
            )
        header = self._headers[layout]
        return record if header is None else record.model_copy(update={"header": header})
