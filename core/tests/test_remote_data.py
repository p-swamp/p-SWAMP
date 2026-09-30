"""The remote data client against the stub, in-process, and its failures."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from pydantic import ValidationError
from remote_data_stub import create_app
from support import ListClient, frame

from pswamp_core.datagateway import DataGateway, TimeRange
from pswamp_core.datagateway.clients.remote_data import RemoteDataClient
from pswamp_core.messages import RemoteDataResult
from pswamp_core.testing import DataClientConformance

SERVED = ListClient("served")


def over(app_or_handler) -> RemoteDataClient:
    """A client whose connection is ``app_or_handler``: the stub app, or a mock."""
    if callable(app_or_handler) and not hasattr(app_or_handler, "routes"):
        transport = httpx.MockTransport(app_or_handler)
    else:
        transport = httpx.ASGITransport(app=app_or_handler)
    return RemoteDataClient("remote", "http://stub", http_client=httpx.AsyncClient(transport=transport, base_url="http://stub"))


class TestRemoteDataClientOverTheStub(DataClientConformance):
    @pytest.fixture
    def client_under_test(self):
        return over(create_app(SERVED))

    @pytest.fixture
    def conformance_records(self):
        return SERVED.frames


def test_a_result_line_has_the_shape_of_its_kind():
    assert RemoteDataResult.for_record(frame(0)).to_line().endswith(b"\n")
    for bad in ({"kind": "record"}, {"kind": "end"}, {"kind": "error"}):
        with pytest.raises(ValidationError):
            RemoteDataResult(**bad)


async def test_an_unreachable_service_is_named_in_the_error():
    client = RemoteDataClient("remote", "http://127.0.0.1:9", timeout=timedelta(seconds=2))
    with pytest.raises(ConnectionError, match="127.0.0.1:9"):
        await client.coverage()
    await client.close()


def lines(*parts: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"".join(parts))

    return handler


async def test_an_error_line_or_a_missing_end_fails_the_stream():
    record = RemoteDataResult.for_record(frame(0)).to_line()
    failed = over(lines(record, RemoteDataResult(kind="error", error="disk on fire").to_line()))
    with pytest.raises(RuntimeError, match="disk on fire"):
        [r async for r in failed.consume(TimeRange())]
    cut = over(lines(record))
    with pytest.raises(RuntimeError, match="without an end line"):
        [r async for r in cut.consume(TimeRange())]


async def test_a_gateway_reads_a_chunk_through_the_service():
    gateway = DataGateway([over(create_app(SERVED))])
    coverage = await gateway.coverage()
    chunk = [f async for f in await gateway.consume(coverage.start, SERVED.frames[3].timestamp)]
    assert [f.timestamp for f in chunk] == [f.timestamp for f in SERVED.frames[:3]]
    await gateway.close()
