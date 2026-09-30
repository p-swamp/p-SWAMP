"""The gateway: named sources, one active, opened on first use; and the
reference clients passing the conformance suite."""

from __future__ import annotations

import pytest
from support import ListClient, TickingClient, at, frame

from pswamp_core.datagateway import DataGateway
from pswamp_core.testing import DataClientConformance


class TestListClient(DataClientConformance):
    @pytest.fixture
    def client_under_test(self):
        return ListClient()

    @pytest.fixture
    def conformance_records(self, client_under_test):
        return client_under_test.frames


class TestTickingClient(DataClientConformance):
    @pytest.fixture
    def client_under_test(self):
        return TickingClient()


async def test_the_first_source_is_active_until_a_switch():
    gateway = DataGateway([ListClient("sample"), TickingClient("live")])
    assert gateway.sources == ["sample", "live"]
    assert (gateway.source, gateway.live) == ("sample", False)
    gateway.switch("live")
    assert (gateway.source, gateway.live, gateway.kind("sample")) == ("live", True, "history")
    with pytest.raises(ValueError):
        gateway.switch("nope")


def test_a_gateway_refuses_no_clients_or_two_with_one_name():
    with pytest.raises(ValueError):
        DataGateway([])
    with pytest.raises(ValueError):
        DataGateway([ListClient("x"), ListClient("x")])


async def test_a_client_is_opened_on_first_use_and_closed_with_the_gateway():
    sample, live = ListClient("sample"), TickingClient("live")
    gateway = DataGateway([sample, live])
    await gateway.coverage()
    await gateway.consume()
    assert (sample.opened, live.opened) == (1, 0)
    await gateway.close()
    assert sample.closed == 1


async def test_a_stream_is_one_range_of_the_active_source():
    gateway = DataGateway([ListClient("sample", [frame(i) for i in range(5)])])
    assert await gateway.coverage() is not None
    chunk = [f.timestamp async for f in await gateway.consume(at(1), at(3))]
    assert chunk == [at(1), at(2)]
    onwards = [f.timestamp async for f in await gateway.consume(at(3))]
    assert onwards == [at(3), at(4)]
