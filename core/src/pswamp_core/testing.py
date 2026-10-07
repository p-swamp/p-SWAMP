# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SourceConformance``: the pytest cases a data source must pass.

It is for a ``SourceModule``. Inherit it in a test class and supply two
fixtures::

    class TestMySource(SourceConformance):
        @pytest.fixture
        def source_under_test(self):
            return MySource()

        @pytest.fixture
        def conformance_records(self):        # history sources: every record it holds, in order
            return [...]

The cases follow the source's ``kind``, and read it through a ``SourceSet``, as
the core does: a history's coverage spans its records, its ranges are half open,
a seek lands on the record, a stream closed early can be read again; a live
feed has no coverage and a bounded tail ends inside its window. They also check
that the sync and async halves agree (``read`` equals ``aread``, ``coverage``
equals ``acoverage``) and that only declared ``outputs`` are produced. The sync
cases are plain functions, so a source written as ``aread`` is driven by
``read``, which needs no running event loop. A live source's fixture needs no
records.

Imports pytest, so only tests import this.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from .sources import SourceModule, SourceSet
from .util.time import utcnow

__all__ = ["SourceConformance"]

#: A bounded live tail's length, and how long it may take to return.
_LIVE_WINDOW = timedelta(seconds=0.3)
_LIVE_TIMEOUT = 3.0


def _key(record) -> tuple:
    return (record.timestamp, record.mRID)


def _ordered_utc(records) -> None:
    previous = None
    for record in records:
        assert record.timestamp is not None and record.timestamp.utcoffset() == timedelta(0)
        assert previous is None or record.timestamp >= previous
        previous = record.timestamp


async def _drain(stream) -> list:
    return [record async for record in stream]


# --- sources ----------------------------------------------------------------------------


def _only_source(source: SourceModule, kind: str) -> None:
    if source.kind != kind:
        pytest.skip(f"{source.source} is a {source.kind} source")


async def _collect(records) -> list:
    return [record async for record in records]


class _sources:
    """A one-source set, closed on exit."""

    def __init__(self, source: SourceModule) -> None:
        self.sources = SourceSet([source])

    async def __aenter__(self) -> SourceSet:
        return self.sources

    async def __aexit__(self, *exc: object) -> None:
        await self.sources.close()


class SourceConformance:
    """Inherit, supply ``source_under_test`` (and ``conformance_records`` for a
    history), and pytest runs the cases."""

    @pytest.fixture
    def conformance_records(self) -> list:
        return []

    def test_it_declares_its_kind_and_outputs(self, source_under_test):
        source = source_under_test
        assert source.kind in ("history", "live")
        assert source.name and source.outputs and source.model is source.outputs[0]

    # -- history -----------------------------------------------------------------

    async def test_history_coverage_spans_its_records(self, source_under_test, conformance_records):
        _only_source(source_under_test, "history")
        assert conformance_records, "a history source's fixture must list its records"
        _ordered_utc(conformance_records)
        async with _sources(source_under_test) as sources:
            coverage = await sources.coverage()
        assert coverage is not None
        assert coverage.contains(conformance_records[0].timestamp)
        assert coverage.contains(conformance_records[-1].timestamp)

    async def test_history_yields_every_record_in_order(self, source_under_test, conformance_records):
        _only_source(source_under_test, "history")
        async with _sources(source_under_test) as sources:
            got = await _collect(await sources.consume())
        assert [_key(r) for r in got] == [_key(r) for r in conformance_records]

    async def test_history_yields_only_declared_outputs(self, source_under_test, conformance_records):
        _only_source(source_under_test, "history")
        async with _sources(source_under_test) as sources:
            got = await _collect(await sources.consume())
        assert got and all(isinstance(r, tuple(source_under_test.outputs)) for r in got)

    async def test_history_ranges_are_half_open(self, source_under_test, conformance_records):
        _only_source(source_under_test, "history")
        if len(conformance_records) < 4:
            pytest.skip("needs at least four records")
        start, end = conformance_records[1].timestamp, conformance_records[3].timestamp
        async with _sources(source_under_test) as sources:
            got = await _collect(await sources.consume(start, end))
        assert [_key(r) for r in got] == [_key(r) for r in conformance_records if start <= r.timestamp < end]

    async def test_history_seek_lands_on_the_record(self, source_under_test, conformance_records):
        _only_source(source_under_test, "history")
        target = conformance_records[len(conformance_records) // 2]
        async with _sources(source_under_test) as sources:
            stream = await sources.consume(target.timestamp)
            first = await stream.__anext__()
            await stream.aclose()
        assert _key(first) == _key(target)

    async def test_history_can_be_closed_early_and_read_again(self, source_under_test, conformance_records):
        _only_source(source_under_test, "history")
        async with _sources(source_under_test) as sources:
            stream = await sources.consume()
            await stream.__anext__()
            await stream.aclose()
            again = await _collect(await sources.consume())
        assert len(again) == len(conformance_records)

    def test_history_sync_read_equals_aread(self, source_under_test, conformance_records):
        _only_source(source_under_test, "history")
        sync = list(source_under_test.read())
        asynchronous = asyncio.run(_collect(source_under_test.aread()))
        assert [_key(r) for r in sync] == [_key(r) for r in asynchronous]
        assert [_key(r) for r in sync] == [_key(r) for r in conformance_records]
        if len(conformance_records) >= 4:
            start, end = conformance_records[1].timestamp, conformance_records[3].timestamp
            assert [_key(r) for r in source_under_test.read(start, end)] == [
                _key(r) for r in conformance_records if start <= r.timestamp < end
            ]

    def test_history_sync_coverage_equals_acoverage(self, source_under_test, conformance_records):
        _only_source(source_under_test, "history")
        coverage = source_under_test.coverage()
        assert coverage is not None and coverage == asyncio.run(source_under_test.acoverage())
        assert all(coverage.contains(r.timestamp) for r in conformance_records)

    # -- live --------------------------------------------------------------------

    async def test_live_has_no_coverage(self, source_under_test):
        _only_source(source_under_test, "live")
        async with _sources(source_under_test) as sources:
            assert await sources.coverage() is None

    async def test_a_bounded_live_tail_ends_inside_its_window(self, source_under_test):
        _only_source(source_under_test, "live")
        async with _sources(source_under_test) as sources:
            start = utcnow()
            stream = await sources.consume(start, start + _LIVE_WINDOW)
            got = await asyncio.wait_for(_drain(stream), _LIVE_TIMEOUT)
        _ordered_utc(got)
        assert all(start <= r.timestamp < start + _LIVE_WINDOW for r in got)
        assert all(isinstance(r, tuple(source_under_test.outputs)) for r in got)

    async def test_a_live_tail_can_be_closed_early_and_reopened(self, source_under_test):
        _only_source(source_under_test, "live")
        async with _sources(source_under_test) as sources:
            stream = await sources.consume(utcnow())
            try:
                await asyncio.wait_for(stream.__anext__(), 0.2)
            except TimeoutError:
                pass
            await stream.aclose()
            start = utcnow()
            await asyncio.wait_for(_drain(await sources.consume(start, start + _LIVE_WINDOW)), _LIVE_TIMEOUT)

    def test_a_bounded_live_sync_read_ends_inside_its_window(self, source_under_test):
        _only_source(source_under_test, "live")
        assert source_under_test.coverage() is None
        start = utcnow()
        got = list(source_under_test.read(start, start + _LIVE_WINDOW))
        _ordered_utc(got)
        assert all(start <= r.timestamp < start + _LIVE_WINDOW for r in got)
