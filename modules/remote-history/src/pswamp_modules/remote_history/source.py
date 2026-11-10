# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``RemoteHistory``: a history source over a remote data service.

The deployment runs a small REST service in front of whatever store holds its
history; this source speaks the contract (doc/remote-data-integration-contract.md)
and knows nothing of the store::

    REMOTE_URL=http://remote-data-stub:8100
    REMOTE_TIMEOUT=30
    REMOTE_COVERAGE_TIMEOUT=10
    REMOTE_PAGE=30000

- ``acoverage`` is ``GET /v1/coverage``.
- ``aread`` is ``POST /v1/queries``, targeting ``PAGE`` station records and
  finishing the final timestamp: records arrive as streamed NDJSON, read a
  line at a time as the player pulls them. A full page is followed by the next,
  from the instant after its last record, so a range of months is many small
  queries and a gap of weeks costs none. The connection paces the service, and
  closing the stream early (a seek) closes the connection, which is the
  service's cue to stop.
- ``TIMEOUT`` bounds the wait for a response to start and for each line;
  a paused replay reads nothing and is not timed out.
- ``COVERAGE_TIMEOUT`` bounds the coverage call, which a seek and a switch
  to this source wait on.

Written as async code, because the data is: a script calls the synchronous
``read`` and ``coverage``, which drive these on a private event loop. A client
is made per call (one ``aread``, all its pages) and closed at its end (an
``httpx`` connection pool belongs to the loop it was made in, and each of those
calls may run in its own), unless ``http_client`` supplies one, as the tests do.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from collections.abc import AsyncIterator, AsyncGenerator
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx

from pswamp_core.time_range import TimeRange
from pswamp_core.playable import Playable
from pswamp_core.settings import EnvSetting
from pswamp_core.sources import SourceModule
from pswamp_core.util.time import ensure_utc
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.remote_data import (
    RemoteDataQuery,
    RESULT_ADAPTER,
    ErrorResponse,
    ErrorMessage,
    EndResponse,
    RecordResponse,
    RecordMessage,
)

__all__ = ["RemoteHistory"]

_MICROSECOND = timedelta(microseconds=1)


class RemoteHistory(Playable, SourceModule):
    """A history from a remote data service. ``http_client`` (an
    ``httpx.AsyncClient``) replaces the connection, for tests."""

    name = "remote-history"
    kind = "history"
    outputs = (PmuFrame,)
    env_settings = (
        EnvSetting("URL", "Base URL of the remote data service, e.g. http://remote-data:8100", required=True),
        EnvSetting("TIMEOUT", "Seconds to wait for an answer to start, and for each line", default="30", kind="seconds"),
        EnvSetting("COVERAGE_TIMEOUT", "Seconds to wait for the coverage, which a seek waits on", default="10", kind="seconds"),
        EnvSetting("PAGE", "Records per query; a full page is followed by the next", default="30000", kind="int"),
    )

    def __init__(
        self,
        source: str | None = None,
        *,
        http_client: Any | None = None,
        **settings: Any,
    ) -> None:
        super().__init__(source, **settings)
        self.url: str = self.settings.url.rstrip("/")
        self.timeout: float = self.settings.timeout.total_seconds()
        self.coverage_timeout: float = self.settings.coverage_timeout.total_seconds()
        self.page: int = self.settings.page
        if not isinstance(self.page, int) or self.page < 1:
            raise ValueError(f"{type(self).__name__}: PAGE must be a positive number of records, not {self.page!r}")
        self._http_client = http_client


    @contextlib.asynccontextmanager
    async def _http(self) -> AsyncGenerator[Any, None]:
        if self._http_client is not None:
            yield self._http_client
            return
        async with httpx.AsyncClient(base_url=self.url, timeout=10.0) as http:
            yield http


    async def acoverage(self) -> TimeRange | None:
        try:
            async with self._http() as http:
                response = await http.get(
                    "/v1/coverage", timeout=self.coverage_timeout
                )
        except Exception as error:  # the message a person sees when the service is down
            raise ConnectionError(f"cannot reach {self.url or 'the service'}: {type(error).__name__}: {error}") from error
        response.raise_for_status()
        body = response.json()

        if body.get("start") is None:
            return None
        return TimeRange(
            _instant(body["start"]),
            None if body.get("end") is None else _instant(body["end"])
        )


    async def aread(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        stations: list[str] | None = None,
    ) -> AsyncIterator[PmuFrame]:
        window = TimeRange(start, end)
        request_id = uuid4().hex
        page_start = window.start
        async with self._http() as http:
            for page in itertools.count(1):
                page_id = f"{request_id}.{page}"
                query = RemoteDataQuery(
                    start=page_start,
                    end=window.end,
                    stations=stations,
                    limit=self.page,
                )
                received = 0
                last: datetime | None = None
                group: list[RecordMessage] = []
                wanted = TimeRange(page_start, window.end)  # a service may send more; it is dropped
                # aclosing: a stream closed early (a seek) closes this page's connection at once.
                async with contextlib.aclosing(self._records(http, page_id, query)) as records:
                    async for record in records:
                        received += 1
                        timestamp = ensure_utc(record.msg.ts)
                        if last is not None and timestamp < last:
                            raise RuntimeError(f"{self.source}: records are not in timestamp order")
                        if group and timestamp != last:
                            if wanted.contains(ensure_utc(group[0].ts)):
                                yield self._frame(group)
                            group = []
                        last = timestamp
                        group.append(record.msg)
                if group and wanted.contains(ensure_utc(group[0].ts)):
                    yield self._frame(group)
                if received < self.page or last is None:
                    return  # the service has no more
                following = last + _MICROSECOND
                if page_start is not None and following <= page_start:
                    raise RuntimeError(f"{self.source}: page {page_id} did not move past {page_start.isoformat()}")
                if window.end is not None and following >= window.end:
                    return
                page_start = following


    async def _records(
        self,
        http: Any,
        request_id: str,
        query: RemoteDataQuery,
    ) -> AsyncIterator[RecordResponse]:
        """One page, finishing the last timestamp even if it exceeds the limit."""
        request = http.build_request(
            "POST", "/v1/queries", json=query.model_dump(mode="json"),
            headers={"x-request-id": request_id}, timeout=httpx.Timeout(self.timeout, read=None)
        )
        try:
            async with asyncio.timeout(self.timeout):
                response = await http.send(request, stream=True)
        except Exception as error:
            raise ConnectionError(
                f"{self.source}: request {request_id} to {self.url} failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if response.status_code != 200:
                await response.aread()
                raise RuntimeError(f"{self.source}: query refused: HTTP {response.status_code} {response.text[:200]}")
            lines = response.aiter_lines()
            sent = 0
            last: datetime | None = None
            while True:
                try:
                    async with asyncio.timeout(self.timeout):
                        line = await anext(lines)
                except StopAsyncIteration:
                    raise RuntimeError(
                        f"{self.source}: the answer to request {request_id} stopped without an end line"
                    ) from None
                if not line.strip():
                    continue
                result = RESULT_ADAPTER.validate_json(line)
                match result:
                    case EndResponse():
                        return
                    case ErrorResponse(msg=ErrorMessage(message=message)):
                        raise RuntimeError(f"{self.source}: request {request_id} failed at the service: {message}")
                    case RecordResponse():
                        timestamp = ensure_utc(result.msg.ts)
                        if query.limit is not None and sent >= query.limit and timestamp != last:
                            return  # the service ignored the limit
                        sent += 1
                        last = timestamp
                        yield result
        finally:
            await response.aclose()  # closing early closes the connection: the service stops


    def _frame(self, records: list[RecordMessage]) -> PmuFrame:
        station: list[str] = []
        channel: list[str] = []
        measurement: list[str] = []
        units: list[str] = []
        values: list[float | None] = []
        seen: set[str] = set()
        for record in records:
            if record.id in seen:
                raise RuntimeError(f"{self.source}: duplicate station {record.id!r} at {record.ts}")
            seen.add(record.id)
            station.extend([record.id, record.id])
            channel.extend(["f", "df"])
            measurement.extend(["f", "df"])
            units.extend(["Hz", "Hz/s"])
            values.extend([record.frequency, record.rocof])
            for phasor in record.phasors:
                voltage = phasor.kind == "U"
                station.extend([record.id, record.id])
                channel.extend([phasor.name, phasor.name])
                measurement.extend([
                    "V_Magnitude" if voltage else "I_Magnitude",
                    "V_Angle"     if voltage else "I_Angle",
                ])
                units.extend(["kV" if voltage else "A", "deg"])
                values.extend([phasor.magnitude / 1000 if voltage else phasor.magnitude, phasor.angle])
        return PmuFrame(
            timestamp=ensure_utc(records[0].ts), mRID=self.source,
            header=PmuHeader(station=station, channel=channel, measurement=measurement, units=units, data_rate=50.0),
            values=values,
        )


def _instant(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
