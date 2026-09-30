# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``DataClientConformance``: the pytest cases a data client must pass.

Inherit it in a test class and supply two fixtures::

    class TestMyClient(DataClientConformance):
        @pytest.fixture
        def client_under_test(self):
            return MyClient("mine")

        @pytest.fixture
        def conformance_records(self):        # history clients: every record it holds, in order
            return [...]

The cases follow the client's ``kind``, and read it through a
``DataGateway``, as the core does. Imports pytest, so only tests import this.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from .datagateway import DataClient, DataGateway
from .util.time import utcnow

__all__ = ["DataClientConformance"]

#: A bounded live tail's length, and how long it may take to return.
_LIVE_WINDOW = timedelta(seconds=0.3)
_LIVE_TIMEOUT = 3.0


def _key(record) -> tuple:
    return (record.timestamp, record.mRID)


def _only(client: DataClient, kind: str) -> None:
    if client.kind != kind:
        pytest.skip(f"{client.name} is a {client.kind} client")


def _ordered_utc(records) -> None:
    previous = None
    for record in records:
        assert record.timestamp is not None and record.timestamp.utcoffset() == timedelta(0)
        assert previous is None or record.timestamp >= previous
        previous = record.timestamp


class DataClientConformance:
    """Inherit, supply the fixtures, and pytest runs the cases."""

    @pytest.fixture
    def conformance_records(self) -> list:
        return []

    async def test_it_is_a_history_or_a_live_feed(self, client_under_test):
        assert client_under_test.kind in ("history", "live")

    # -- history -----------------------------------------------------------------

    async def test_history_coverage_spans_its_records(self, client_under_test, conformance_records):
        _only(client_under_test, "history")
        assert conformance_records, "a history client's fixture must list its records"
        _ordered_utc(conformance_records)
        async with _gateway(client_under_test) as gateway:
            coverage = await gateway.coverage()
        assert coverage is not None
        assert coverage.contains(conformance_records[0].timestamp)
        assert coverage.contains(conformance_records[-1].timestamp)

    async def test_history_yields_every_record_in_order(self, client_under_test, conformance_records):
        _only(client_under_test, "history")
        async with _gateway(client_under_test) as gateway:
            got = [r async for r in await gateway.consume()]
        assert [_key(r) for r in got] == [_key(r) for r in conformance_records]

    async def test_history_ranges_are_half_open(self, client_under_test, conformance_records):
        _only(client_under_test, "history")
        if len(conformance_records) < 4:
            pytest.skip("needs at least four records")
        start, end = conformance_records[1].timestamp, conformance_records[3].timestamp
        async with _gateway(client_under_test) as gateway:
            got = [r async for r in await gateway.consume(start, end)]
        assert [_key(r) for r in got] == [_key(r) for r in conformance_records if start <= r.timestamp < end]

    async def test_history_seek_lands_on_the_record(self, client_under_test, conformance_records):
        _only(client_under_test, "history")
        target = conformance_records[len(conformance_records) // 2]
        async with _gateway(client_under_test) as gateway:
            stream = await gateway.consume(target.timestamp)
            first = await stream.__anext__()
            await stream.aclose()
        assert _key(first) == _key(target)

    async def test_history_can_be_closed_early_and_read_again(self, client_under_test, conformance_records):
        _only(client_under_test, "history")
        async with _gateway(client_under_test) as gateway:
            stream = await gateway.consume()
            await stream.__anext__()
            await stream.aclose()
            again = [r async for r in await gateway.consume()]
        assert len(again) == len(conformance_records)

    # -- live --------------------------------------------------------------------

    async def test_live_has_no_coverage(self, client_under_test):
        _only(client_under_test, "live")
        async with _gateway(client_under_test) as gateway:
            assert await gateway.coverage() is None

    async def test_a_bounded_live_tail_ends_inside_its_window(self, client_under_test):
        _only(client_under_test, "live")
        async with _gateway(client_under_test) as gateway:
            start = utcnow()
            stream = await gateway.consume(start, start + _LIVE_WINDOW)
            got = await asyncio.wait_for(_drain(stream), _LIVE_TIMEOUT)
        _ordered_utc(got)
        assert all(start <= r.timestamp < start + _LIVE_WINDOW for r in got)

    async def test_a_live_tail_can_be_closed_early_and_reopened(self, client_under_test):
        _only(client_under_test, "live")
        async with _gateway(client_under_test) as gateway:
            stream = await gateway.consume(utcnow())
            try:
                await asyncio.wait_for(stream.__anext__(), 0.2)
            except TimeoutError:
                pass
            await stream.aclose()
            start = utcnow()
            await asyncio.wait_for(_drain(await gateway.consume(start, start + _LIVE_WINDOW)), _LIVE_TIMEOUT)


async def _drain(stream) -> list:
    return [record async for record in stream]


class _gateway:
    """A one-source gateway, closed on exit."""

    def __init__(self, client: DataClient) -> None:
        self.gateway = DataGateway([client])

    async def __aenter__(self) -> DataGateway:
        return self.gateway

    async def __aexit__(self, *exc: object) -> None:
        await self.gateway.close()
