# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The contract's REST surface over a history ``SourceModule``:

    GET  /health/live                     200 {status}
    GET  /health/ready                    200 {status}
    GET  /v1/coverage                    200 {start, end, stations: [{id, name}]}
    POST /v1/queries   RemoteDataQuery    200 NDJSON: station records, then one end or error line

A client that closes the connection has cancelled: Starlette stops the
generator where it stands.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from pswamp_core.log import get_logger
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_models.remote_data import (
    RemoteDataQuery,
    RecordResponse,
    EndResponse,
    ErrorResponse,
    ErrorMessage,
    EndMessage,
)

__all__ = ["create_app"]

logger = get_logger("remote-data-stub")

#: Keeps a proxy from buffering the stream into one blob.
STREAM_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}


def create_app(source: SourceModule) -> FastAPI:
    # A set of one reads the source as the core does: opened on first use, a
    # record without a timestamp dropped, nothing at or past the range's end.
    sources = SourceSet([source])

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await sources.close()


    app = FastAPI(title="p-SWAMP remote data stub", lifespan=lifespan)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}


    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ok"}


    @app.get("/v1/coverage")
    async def coverage() -> dict:
        held = await sources.coverage()
        return {
            "start": held and held.start,
            "end"  : held and held.end,
            "stations": [
                {"id": "NO 12345", "name": "NO 12345 stasjon AB3"},
                {"id": "NO 54321", "name": "NO 54321 stasjon BA1"},
            ],
        }


    @app.post("/v1/queries")
    async def queries(
        query: RemoteDataQuery,
        request: Request,
    ) -> StreamingResponse:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        headers = STREAM_HEADERS.copy()
        headers["x-request-id"] = request_id
        return StreamingResponse(
            answer(request_id, query),
            media_type="application/x-ndjson",
            headers=headers,
        )


    async def answer(request_id: str, query: RemoteDataQuery) -> AsyncIterator[bytes]:
        logger.info(f"query {request_id}: {query.stations} [{query.start}, {query.end}) limit {query.limit}")

        stations = sorted(query.stations if query.stations is not None else ["NO 12345", "NO 54321"])

        step = timedelta(milliseconds=20)
        seq = 1

        try:
            held = await sources.coverage()
            if held is None:
                ts = end = None
            else:
                if held.start is None or held.end is None:
                    raise ValueError("the stub requires finite source coverage")
                start = max(query.start or held.start, held.start)
                end = min(query.end or held.end, held.end)
                steps, remainder = divmod(start - held.start, step)
                ts = held.start + (steps + bool(remainder)) * step
            while ts is not None and end is not None and ts < end and stations:
                for station in stations:
                    yield RecordResponse.test_record(
                        request_id,
                        ts,
                        seq,
                        station_id=station,
                    ).to_line()
                    seq += 1
                if query.limit is not None and seq > query.limit:
                    break
                ts += step
        except Exception as error:  # past the first byte a failure is a line
            yield ErrorResponse(
                mrid = request_id,
                v    = "v1",
                ts   = datetime.now(timezone.utc),
                seq  = seq,
                kind = "error",
                msg  = ErrorMessage(message = f"{type(error).__name__}: {error}"),
            ).to_line()
            return

        yield EndResponse(
            mrid = request_id,
            v    = "v1",
            ts   = datetime.now(timezone.utc),
            seq  = seq,
            kind = "end",
            msg  = EndMessage(count = seq - 1),
        ).to_line()
        logger.info(f"query {request_id}: sent {seq - 1} records")
    return app
