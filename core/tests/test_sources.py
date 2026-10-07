"""``SourceModule`` (the sync/async bridge, settings, class checks), ``SourceSet``,
and ``SourceConformance`` run over three fixture sources."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from support import AsyncListSource, ListSource, TickingSource, frame

from pswamp_core.datagateway import CimReferenceEnricher
from pswamp_core.settings import EnvSetting, MissingSettingError
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.testing import SourceConformance
from pswamp_models.pmu import PmuFrame

# --- conformance, three ways of writing a source --------------------------------------


class TestSyncHistoryConformance(SourceConformance):
    @pytest.fixture
    def source_under_test(self):
        return ListSource()

    @pytest.fixture
    def conformance_records(self):
        return ListSource().frames


class TestAsyncHistoryConformance(SourceConformance):
    @pytest.fixture
    def source_under_test(self):
        return AsyncListSource()

    @pytest.fixture
    def conformance_records(self):
        return AsyncListSource().frames


class TestAsyncLiveConformance(SourceConformance):
    @pytest.fixture
    def source_under_test(self):
        return TickingSource()


# --- the sync/async bridge -----------------------------------------------------------


def test_a_sync_read_needs_no_event_loop_and_stops_at_the_end():
    source = ListSource()
    assert [f.timestamp for f in source.read()] == [f.timestamp for f in source.frames]


def test_an_async_source_is_read_synchronously_on_a_private_loop():
    source = AsyncListSource()
    got = list(source.read(source.frames[2].timestamp, source.frames[5].timestamp))
    assert [f.timestamp for f in got] == [f.timestamp for f in source.frames[2:5]]
    assert source.coverage().start == source.frames[0].timestamp


async def test_an_async_source_refuses_a_sync_read_inside_a_running_loop():
    source = AsyncListSource()
    with pytest.raises(RuntimeError, match="running event loop.*aread"):
        source.read()
    with pytest.raises(RuntimeError, match="acoverage"):
        source.coverage()
    assert len([f async for f in source.aread()]) == 20  # the async form works there


@pytest.mark.parametrize("blocking", [False, True])
async def test_a_sync_source_is_read_asynchronously_inline_or_in_a_thread(blocking):
    class Source(ListSource):
        name = f"bridge-{blocking}"

    Source.blocking = blocking
    assert len([f async for f in Source().aread()]) == 20
    assert await Source().acoverage() == Source().coverage()


async def test_closing_an_async_read_closes_the_sync_iterator():
    closed = []

    class Source(ListSource):
        name = "closing"

        def read(self, start=None, end=None):
            try:
                yield from super().read(start, end)
            finally:
                closed.append(True)

    records = Source().aread()
    await records.__anext__()
    await records.aclose()
    assert closed == [True]


def test_open_and_close_pair_sync_and_async_and_are_context_managers():
    source = ListSource()
    with source as inside:
        assert inside is source and source.opened == 1
    assert source.closed == 1

    async def use():
        async with ListSource() as other:
            assert other.opened == 1
        return other

    assert asyncio.run(use()).closed == 1


async def test_a_source_opens_once_however_many_ask():
    source = ListSource()
    await source._ensure_open()
    await source._ensure_open()
    assert source.opened == 1
    await source._ensure_closed()
    await source._ensure_closed()
    assert source.closed == 1


# --- settings --------------------------------------------------------------------------


class Configured(SourceModule):
    name = "configured"
    kind = "live"
    env_settings = (
        EnvSetting("PATH", "a file", default="default.txt", kind="path"),
        EnvSetting("RATE", "a rate", kind="float"),
        EnvSetting("URL", "where", required=True),
    )

    def read(self, start=None, end=None):
        return iter(())


def test_settings_come_from_keywords_with_defaults_and_types():
    source = Configured(url="http://x", rate=2.0)  # a script's keywords
    assert source.source == "configured"  # the module's name unless told otherwise
    assert (source.settings.path, source.settings.rate, source.settings.url) == (Path("default.txt"), 2.0, "http://x")
    assert Configured("mine", url="u", path="a.txt").settings.path == Path("a.txt")
    with pytest.raises(MissingSettingError, match="url"):
        Configured()
    with pytest.raises(TypeError, match="no setting nope"):
        Configured(url="u", nope=1)


def test_settings_come_from_the_environment_by_instance_name(monkeypatch):
    monkeypatch.setenv("SAMPLE_URL", "http://env")
    monkeypatch.setenv("SAMPLE_RATE", "2.5")
    source = Configured.from_env("sample")
    assert (source.source, source.settings.url, source.settings.rate) == ("sample", "http://env", 2.5)
    assert Configured.from_env("sample", rate=1.0).settings.rate == 1.0  # an override wins


# --- checked when the class is defined ------------------------------------------------------


class Reading(SourceModule):
    abstract = True

    def read(self, start=None, end=None):
        return iter(())


def test_a_source_class_is_checked_when_defined():
    with pytest.raises(TypeError, match="`name`"):

        class NoName(Reading):
            kind = "live"

    with pytest.raises(TypeError, match="kind"):

        class BadKind(Reading):
            name = "x"
            kind = "sometimes"

    with pytest.raises(TypeError, match="read.*aread"):

        class NoRead(SourceModule):
            name = "x"
            kind = "live"

    with pytest.raises(TypeError, match="coverage"):

        class NoCoverage(Reading):
            name = "x"
            kind = "history"

    with pytest.raises(TypeError, match="DataModel"):

        class BadOutputs(Reading):
            name = "x"
            kind = "live"
            outputs = (int,)

    with pytest.raises(TypeError, match="DataModel"):

        class NoOutputs(Reading):
            name = "x"
            kind = "live"
            outputs = ()


def test_an_abstract_base_is_not_checked_and_its_subclasses_are():
    class Sub(Reading):
        name = "sub"
        kind = "live"

    assert Sub.model is PmuFrame and TickingSource.outputs == (PmuFrame,)
    with pytest.raises(TypeError):

        class Unnamed(Reading):
            kind = "live"


# --- SourceSet ----------------------------------------------------------------------------------


async def test_a_source_set_reads_the_active_source_guarded_and_enriched():
    class Odd(SourceModule):
        name = "odd"
        kind = "live"

        async def aread(self, start=None, end=None):
            yield frame(0).model_copy(update={"timestamp": None})  # dropped
            yield frame(1)
            yield frame(2)  # at the end: stops here
            yield frame(3)

    sources = SourceSet([ListSource("rec"), Odd("odd")], enrichers=[CimReferenceEnricher("ref")])
    assert (sources.sources, sources.source, sources.live) == (["rec", "odd"], "rec", False)
    assert (sources.kind("rec"), sources.kind("odd")) == ("history", "live")
    assert (await sources.coverage()).start == frame(0).timestamp
    got = [f async for f in await sources.consume(end=frame(0.1).timestamp)]
    assert [f.timestamp for f in got] == [frame(0).timestamp, frame(0.05).timestamp]
    sources.switch("odd")
    assert sources.live and await sources.coverage() is None
    got = [f async for f in await sources.consume(end=frame(2).timestamp)]
    assert [f.timestamp for f in got] == [frame(1).timestamp]
    assert got[0].header.cimReferenceId == "ref"
    await sources.close()


async def test_a_source_set_opens_lazily_and_closes_what_it_opened():
    rec, other = ListSource("rec"), ListSource("other")
    sources = SourceSet([rec, other], active="other")
    assert sources.source == "other"
    await sources.coverage()
    await sources.consume()
    assert (rec.opened, other.opened) == (0, 1)
    await sources.close()
    assert (rec.closed, other.closed) == (0, 1)


def test_a_source_set_refuses_what_it_cannot_hold():
    with pytest.raises(ValueError, match="at least one"):
        SourceSet([])
    with pytest.raises(ValueError, match="two sources"):
        SourceSet([ListSource("a"), ListSource("a")])
    with pytest.raises(ValueError, match="no source named 'z'"):
        SourceSet([ListSource("a")], active="z")
    with pytest.raises(ValueError, match="no source named 'z'"):
        SourceSet([ListSource("a")]).switch("z")
