# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``RemoteDataClient``: a history data client over a remote data service.

The deployment runs a small REST service in front of whatever store holds its
history; this client speaks the contract (doc/remote-data-integration-contract.md)
and knows nothing of the store::

    PMU_TEST_STREAMER_DATA_CLIENTS=...,remote:pswamp_core.datagateway.clients.remote_data:RemoteDataClient
    REMOTE_URL=http://remote-data-stub:8100
    REMOTE_TIMEOUT=30

- ``coverage`` is ``GET /v1/coverage?model=pmu.frame``.
- ``consume`` is ``POST /v1/queries``; the records come back as that call's
  streamed NDJSON response, read a line at a time as the player pulls them.
  So the connection paces the service, and closing the stream early (a seek)
  closes the connection, which is the service's cue to stop.
- ``TIMEOUT`` bounds the wait for the response to start and for each line;
  a paused replay reads nothing and is not timed out.

Needs the ``remote-data`` extra (httpx), imported where it is used.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...messages.pmu import PmuFrame
from ...messages.remote_data import RemoteDataQuery, RemoteDataResult
from ...settings import EnvSetting
from ...util.time import ensure_utc
from ..data_client import DataClient
from ..time_range import TimeRange

__all__ = ["RemoteDataClient"]


class RemoteDataClient(DataClient):
    """A history from a remote data service. ``http_client`` (an
    ``httpx.AsyncClient``) replaces the connection, for tests."""

    kind = "history"
    env_settings = (
        EnvSetting("URL", "Base URL of the remote data service, e.g. http://remote-data:8100", required=True),
        EnvSetting("TIMEOUT", "Seconds to wait for an answer to start, and for each line", default="30", kind="seconds"),
    )

    def __init__(
        self,
        name: str = "remote",
        url: str = "",
        *,
        timeout: timedelta = timedelta(seconds=30),
        http_client: Any | None = None,
    ) -> None:
        super().__init__(name)
        self.url = url.rstrip("/")
        self.timeout = timeout.total_seconds()
        self._http = http_client
        self._owns_http = http_client is None

    def _client(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.AsyncClient(base_url=self.url, timeout=10.0)
        return self._http

    async def close(self) -> None:
        if self._owns_http and self._http is not None:
            http, self._http = self._http, None
            await http.aclose()

    async def coverage(self) -> TimeRange | None:
        try:
            response = await self._client().get("/v1/coverage", params={"model": self.model.topic})
        except Exception as error:  # the message a person sees when the service is down
            raise ConnectionError(f"cannot reach {self.url or 'the service'}: {type(error).__name__}: {error}") from error
        response.raise_for_status()
        body = response.json()
        if body.get("start") is None:
            return None
        return TimeRange(_instant(body["start"]), None if body.get("end") is None else _instant(body["end"]))

    async def consume(self, time_range: TimeRange) -> AsyncIterator[PmuFrame]:
        import httpx

        http = self._client()
        query = RemoteDataQuery(query_id=uuid4().hex, model=self.model.topic, start=time_range.start, end=time_range.end)
        request = http.build_request(
            "POST", "/v1/queries", json=query.model_dump(mode="json"), timeout=httpx.Timeout(10.0, read=None)
        )
        try:
            async with asyncio.timeout(self.timeout):
                response = await http.send(request, stream=True)
        except Exception as error:
            raise ConnectionError(f"{self.name}: query {query.query_id} to {self.url} failed: {type(error).__name__}: {error}") from error
        try:
            if response.status_code != 200:
                await response.aread()
                raise RuntimeError(f"{self.name}: query refused: HTTP {response.status_code} {response.text[:200]}")
            lines = response.aiter_lines()
            while True:
                try:
                    async with asyncio.timeout(self.timeout):
                        line = await anext(lines)
                except StopAsyncIteration:
                    raise RuntimeError(f"{self.name}: the answer to query {query.query_id} stopped without an end line") from None
                if not line.strip():
                    continue
                result = RemoteDataResult.model_validate_json(line)
                if result.kind == "end":
                    return
                if result.kind == "error":
                    raise RuntimeError(f"{self.name}: query {query.query_id} failed at the service: {result.error}")
                if result.model == self.model.topic:
                    record = self.model.model_validate(result.record)
                    if time_range.contains(record.timestamp):
                        yield record
        finally:
            await response.aclose()  # closing early closes the connection: the service stops


def _instant(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
