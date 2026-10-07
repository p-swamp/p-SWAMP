# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``RemoteHistory``: a history source over a remote data service.

The deployment runs a small REST service in front of whatever store holds its
history; this source speaks the contract (doc/remote-data-integration-contract.md)
and knows nothing of the store::

    REMOTE_URL=http://remote-data-stub:8100
    REMOTE_TIMEOUT=30

- ``acoverage`` is ``GET /v1/coverage?model=pmu.frame``.
- ``aread`` is ``POST /v1/queries``; the records come back as that call's
  streamed NDJSON response, read a line at a time as the player pulls them.
  So the connection paces the service, and closing the stream early (a seek)
  closes the connection, which is the service's cue to stop.
- ``TIMEOUT`` bounds the wait for the response to start and for each line;
  a paused replay reads nothing and is not timed out.

Written as async code, because the data is: a script calls the synchronous
``read`` and ``coverage``, which drive these on a private event loop. A client
is made per call and closed at its end (an ``httpx`` connection pool belongs to
the loop it was made in, and each of those calls may run in its own), unless
``http_client`` supplies one, as the tests do.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx

from pswamp_core.time_range import TimeRange
from pswamp_core.playable import Playable
from pswamp_core.settings import EnvSetting
from pswamp_core.sources import SourceModule
from pswamp_core.util.time import ensure_utc
from pswamp_models.pmu import PmuFrame
from pswamp_models.remote_data import RemoteDataQuery, RemoteDataResult

__all__ = ["RemoteHistory"]


class RemoteHistory(Playable, SourceModule):
    """A history from a remote data service. ``http_client`` (an
    ``httpx.AsyncClient``) replaces the connection, for tests."""

    name = "remote-history"
    kind = "history"
    outputs = (PmuFrame,)
    env_settings = (
        EnvSetting("URL", "Base URL of the remote data service, e.g. http://remote-data:8100", required=True),
        EnvSetting("TIMEOUT", "Seconds to wait for an answer to start, and for each line", default="30", kind="seconds"),
    )

    def __init__(self, source: str | None = None, *, http_client: Any | None = None, **settings: Any) -> None:
        super().__init__(source, **settings)
        self.url: str = self.settings.url.rstrip("/")
        self.timeout: float = self.settings.timeout.total_seconds()
        self._http_client = http_client

    @contextlib.asynccontextmanager
    async def _http(self) -> AsyncIterator[Any]:
        if self._http_client is not None:
            yield self._http_client
            return
        async with httpx.AsyncClient(base_url=self.url, timeout=10.0) as http:
            yield http

    async def acoverage(self) -> TimeRange | None:
        try:
            async with self._http() as http:
                response = await http.get("/v1/coverage", params={"model": self.model.topic})
        except Exception as error:  # the message a person sees when the service is down
            raise ConnectionError(f"cannot reach {self.url or 'the service'}: {type(error).__name__}: {error}") from error
        response.raise_for_status()
        body = response.json()
        if body.get("start") is None:
            return None
        return TimeRange(_instant(body["start"]), None if body.get("end") is None else _instant(body["end"]))

    async def aread(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterator[PmuFrame]:
        window = TimeRange(start, end)
        query = RemoteDataQuery(query_id=uuid4().hex, model=self.model.topic, start=window.start, end=window.end)
        async with self._http() as http:
            request = http.build_request(
                "POST", "/v1/queries", json=query.model_dump(mode="json"), timeout=httpx.Timeout(10.0, read=None)
            )
            try:
                async with asyncio.timeout(self.timeout):
                    response = await http.send(request, stream=True)
            except Exception as error:
                raise ConnectionError(
                    f"{self.source}: query {query.query_id} to {self.url} failed: {type(error).__name__}: {error}"
                ) from error
            try:
                if response.status_code != 200:
                    await response.aread()
                    raise RuntimeError(f"{self.source}: query refused: HTTP {response.status_code} {response.text[:200]}")
                lines = response.aiter_lines()
                while True:
                    try:
                        async with asyncio.timeout(self.timeout):
                            line = await anext(lines)
                    except StopAsyncIteration:
                        raise RuntimeError(
                            f"{self.source}: the answer to query {query.query_id} stopped without an end line"
                        ) from None
                    if not line.strip():
                        continue
                    result = RemoteDataResult.model_validate_json(line)
                    if result.kind == "end":
                        return
                    if result.kind == "error":
                        raise RuntimeError(f"{self.source}: query {query.query_id} failed at the service: {result.error}")
                    if result.model == self.model.topic:
                        record = self.model.model_validate(result.record)
                        if window.contains(record.timestamp):
                            yield record
            finally:
                await response.aclose()  # closing early closes the connection: the service stops


def _instant(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


