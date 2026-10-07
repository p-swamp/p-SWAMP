# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The contract's REST surface over a history ``SourceModule``:

    GET  /healthz                         200 {status}
    GET  /v1/coverage?model=pmu.frame     200 {model, start, end} | 404 unknown model
    POST /v1/queries   RemoteDataQuery    200 NDJSON: record lines, then one end or error line

A client that closes the connection has cancelled: Starlette stops the
generator where it stands.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from pswamp_core.log import get_logger
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_models.remote_data import RemoteDataQuery, RemoteDataResult

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

    def known(model: str) -> None:
        if model != source.model.topic:
            raise HTTPException(404, f"no such model: {model!r}")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/coverage")
    async def coverage(model: str) -> dict:
        known(model)
        held = await sources.coverage()
        return {"model": model, "start": held and held.start, "end": held and held.end}

    @app.post("/v1/queries")
    async def queries(query: RemoteDataQuery) -> StreamingResponse:
        known(query.model)  # refused while a status code can still say so
        return StreamingResponse(answer(query), media_type="application/x-ndjson", headers=STREAM_HEADERS)

    async def answer(query: RemoteDataQuery) -> AsyncIterator[bytes]:
        sent = 0
        logger.info("query %s: %s [%s, %s)", query.query_id, query.model, query.start, query.end)
        stream = None
        try:
            stream = await sources.consume(query.start, query.end)
            async for record in stream:
                yield RemoteDataResult.for_record(record).to_line()
                sent += 1
        except Exception as error:  # past the first byte a failure is a line
            yield RemoteDataResult(kind="error", error=f"{type(error).__name__}: {error}").to_line()
            return
        finally:
            if stream is not None:
                await stream.aclose()
        logger.info("query %s: sent %d records", query.query_id, sent)
        yield RemoteDataResult(kind="end", count=sent).to_line()

    return app
