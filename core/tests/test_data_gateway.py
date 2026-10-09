"""The gateway: named sources, one active, opened on first use; and the
reference clients passing the conformance suite."""

from __future__ import annotations

import pytest
from support import ListClient, TickingClient, at, frame, measurement

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


async def test_a_stream_stamps_its_id_and_a_running_number_on_each_frame():
    gateway = DataGateway([ListClient("sample", [frame(i) for i in range(5)])])
    first = await gateway.consume(at(0), at(4))
    read = [f async for f in first]
    assert {f.stream for f in read} == {first.id}
    assert [f.seq for f in read] == [0, 1, 2, 3]
    again = await gateway.consume(at(2), at(4))  # the same instants, read in another pass
    reread = [f async for f in again]
    assert again.id != first.id and {f.stream for f in reread} == {again.id}
    assert [(f.timestamp, f.seq) for f in reread] == [(at(2), 0), (at(3), 1)]


async def test_a_record_class_without_those_fields_passes_through_as_it_is():
    records = [measurement(i) for i in range(3)]
    gateway = DataGateway([ListClient("numbers", records)])
    read = [r async for r in await gateway.consume(at(0), at(3))]
    assert all(got is sent for got, sent in zip(read, records, strict=True))
