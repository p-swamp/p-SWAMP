"""The RT sim (CIM) source: the conformance every source passes, and what is its own: it runs in real
time, publishes one column group per PMU Analog of the graph, follows the graph (a breaker opened in
the store shows in the frames), survives a store that fails to answer, and stops cleanly. Over the
three-substation sample grid."""

from __future__ import annotations

import asyncio
import multiprocessing
from datetime import timedelta
from itertools import islice

import numpy as np
import pytest

from pswamp_core.cim import SAMPLE_GRID, CimSettings, stage
from pswamp_core.cim.testing import edit, reset
from pswamp_core.playable import Playable
from pswamp_core.testing import SourceConformance
from pswamp_core.util.time import utcnow
from pswamp_core.command_routing import CommandRefused
from pswamp_models.cim import CimEdits
from pswamp_models.pmu import PmuFrame
from pswamp_models.rtsim import OperateSwitchCommand, SimEvent, TripBranchCommand
from pswamp_modules.rtsim_from_cim import RtsimFromCimSource
from pswamp_modules.rtsim_from_cim.follow import COMMANDS
from pswamp_modules.rtsim_from_cim import follow as follow_module
from pswamp_modules.rtsim_from_cim import source as source_module

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
BAY_BREAKER = "3f5e0000-0000-4000-8000-0000000000a1"

needs_profiles = pytest.mark.skipif(not stage(SETTINGS).writable, reason="the CGMES vocabularies are not available to LazyCIM")


def make(**settings) -> RtsimFromCimSource:
    return RtsimFromCimSource(graph=SETTINGS, **settings)


@pytest.fixture(autouse=True)
def pristine_graph():
    yield
    if stage(SETTINGS).writable:
        reset(SETTINGS)


class TestRtsimFromCimConformance(SourceConformance):
    @pytest.fixture
    def source_under_test(self):
        return make()


class Run:
    """The source's stream read in the background, as a run's router reads it."""

    def __init__(self, source: RtsimFromCimSource) -> None:
        self.source = source
        self.frames: list[PmuFrame] = []
        #: What it said beside its frames: ``CimEdits`` and ``SimEvent``.
        self.said: list = []

    async def __aenter__(self) -> Run:
        self.task = asyncio.create_task(self._pump())
        return self

    async def _pump(self) -> None:
        async for record in self.source.aread():
            (self.frames if isinstance(record, PmuFrame) else self.said).append(record)

    async def __aexit__(self, *exc) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def until(self, condition, timeout: float = 60.0) -> None:
        async def poll() -> None:
            while not condition():
                if self.task.done():
                    self.task.result()
                    raise AssertionError("the stream ended")
                await asyncio.sleep(0.01)

        await asyncio.wait_for(poll(), timeout)


def angles(frame: PmuFrame) -> np.ndarray:
    """The voltage angles, against the first station's."""
    values = np.array([v for v, m in zip(frame.values, frame.header.measurement, strict=True) if m == "V_Angle"], dtype=float)
    return values - values[0]


def test_it_is_a_live_source_that_reads_the_graph_takes_commands_and_is_not_playable():
    assert (RtsimFromCimSource.name, RtsimFromCimSource.kind, RtsimFromCimSource.cim) == ("rtsim-from-cim", "live", True)
    assert RtsimFromCimSource.outputs == (PmuFrame, CimEdits, SimEvent)
    assert RtsimFromCimSource.commands == COMMANDS
    assert not issubclass(RtsimFromCimSource, Playable)


def test_a_transformer_is_operated_as_a_line():
    from pswamp_models.rtsim import OperateLineCommand

    ids = {"lines": {"L": "line-mrid"}, "transformers": {"T": "trafo-mrid"}}
    source_module._check(OperateLineCommand(mRID="trafo-mrid", in_service=False), ids)  # accepted
    with pytest.raises(CommandRefused, match="no line or transformer"):
        source_module._check(OperateLineCommand(mRID="nowhere", in_service=False), ids)


def test_a_command_before_the_simulation_runs_is_refused():
    with pytest.raises(CommandRefused, match="not running"):
        make().validate(OperateSwitchCommand(mRID=BAY_BREAKER, open=True))


async def commanded(apart: bool, monkeypatch) -> None:
    """A breaker opened by command shows in the frames and is reported for the graph, which the source
    never writes; an object the simulation lacks is refused before it is sent."""
    if apart:
        monkeypatch.setattr(source_module, "follows_apart", lambda settings: True)
    source = make()
    async with Run(source) as run:
        await run.until(lambda: len(run.frames) >= 25)
        before = angles(run.frames[-1])
        with pytest.raises(CommandRefused, match="no switch"):
            source.validate(OperateSwitchCommand(mRID="nowhere", open=True))
        command = OperateSwitchCommand(mRID=BAY_BREAKER, open=True)
        source.validate(command)
        (event,) = await source.arun_command(command)
        assert isinstance(event, SimEvent) and event.request_id == command.request_id
        await run.until(lambda: any(isinstance(m, CimEdits) for m in run.said), timeout=10)
        (edits,) = [m for m in run.said if isinstance(m, CimEdits)]
        assert (edits.request_id, edits.edits[0].mRID, edits.edits[0].value) == (command.request_id, BAY_BREAKER, True)
        await run.until(lambda: np.max(np.abs(angles(run.frames[-1]) - before)) > 0.1, timeout=10)
        with pytest.raises(CommandRefused, match="already open"):
            await source.arun_command(OperateSwitchCommand(mRID=BAY_BREAKER, open=True))
        # A disturbance: announced, never reported for the graph.
        await source.arun_command(TripBranchCommand(mRID="3f5e0000-0000-4000-8000-000000000024"))
        await asyncio.sleep(1)
        assert len([m for m in run.said if isinstance(m, CimEdits)]) == 1


async def test_a_breaker_commanded_opens_in_the_simulation_and_is_reported_for_the_graph(monkeypatch):
    await commanded(apart=False, monkeypatch=monkeypatch)


async def test_commands_reach_a_controller_in_a_process_of_its_own(monkeypatch):
    await commanded(apart=True, monkeypatch=monkeypatch)


@needs_profiles
async def test_what_the_simulation_reports_is_taken_however_slow_following_the_graph_is():
    # Following the graph is Python work in the server's process, so it backs off for three times as
    # long as it took; what the simulation reports (a breaker it opened) must not wait for that.
    import time

    source = make()
    async with Run(source) as run:
        await run.until(lambda: len(run.frames) >= 25)
        controller = source._controller
        follow_graph = controller.changes

        def slow() -> list[str]:
            time.sleep(1.5)  # a refresh of a big export
            return follow_graph()

        controller.changes = slow
        await asyncio.sleep(2)  # into its back-off
        sent = time.monotonic()
        await source.arun_command(OperateSwitchCommand(mRID=BAY_BREAKER, open=True))
        await run.until(lambda: any(isinstance(m, CimEdits) for m in run.said), timeout=10)
        assert time.monotonic() - sent < 2.5


def test_the_frame_rate_and_step_must_make_whole_steps_per_frame():
    assert make().steps_per_frame == 2  # 50 Hz at a 10 ms step
    with pytest.raises(ValueError, match="whole number"):
        make(rate=30.0)  # 3.33 steps a frame
    with pytest.raises(ValueError, match="positive"):
        make(dt=0.0)
    with pytest.raises(ValueError, match="positive"):
        make(poll=0.0)


async def test_it_runs_in_real_time_and_publishes_the_graph_s_pmu_analogs():
    async with Run(make()) as run:
        await run.until(lambda: len(run.frames) >= 5)
        began, then = utcnow(), len(run.frames)
        await asyncio.sleep(20)  # long enough to see a drift, not just a burst
        rate = (len(run.frames) - then) / (utcnow() - began).total_seconds()
        assert 45 < rate < 55  # 50 per second: a late frame is made up, not lost
        header = run.frames[0].header
        assert {"Alpha_400", "Beta_400", "Gamma_400"} <= set(header.station) and header.data_rate == 50.0
        steps = [(b.timestamp - a.timestamp).total_seconds() for a, b in zip(run.frames[then:], run.frames[then + 1 :])]
        on_schedule = sum(abs(step - 0.02) < 1e-6 for step in steps)
        assert on_schedule >= 0.99 * len(steps)  # stamped on the schedule, 20 ms apart (a dropped lag is a longer one)
        assert header.analog is None or len(header.analog) == header.n_columns
        stamps = [f.timestamp for f in run.frames]
        assert stamps == sorted(stamps) and abs((stamps[-1] - utcnow()).total_seconds()) < 0.5
        f = [v for v, m in zip(run.frames[-1].values, header.measurement, strict=True) if m == "f"]
        assert np.allclose(f, 50.0, atol=0.01)


async def test_over_a_shared_store_the_graph_is_followed_from_a_process_of_its_own(monkeypatch):
    # An in-process store cannot be shared, so the follower's process fills one of its own: enough to
    # see the frames come at the rate and both processes go with the stream.
    monkeypatch.setattr(source_module, "follows_apart", lambda settings: True)
    ours = {"rtsim-follow", "rtsim-engine"}
    async with Run(make()) as run:
        await run.until(lambda: len(run.frames) >= 5)
        assert ours <= {p.name for p in multiprocessing.active_children()}
        began, then = utcnow(), len(run.frames)
        await asyncio.sleep(5)
        assert 45 < (len(run.frames) - then) / (utcnow() - began).total_seconds() < 55
    assert not ours & {p.name for p in multiprocessing.active_children()}


@needs_profiles
async def test_a_breaker_opened_in_the_graph_shows_in_the_frames():
    async with Run(make()) as run:
        await run.until(lambda: len(run.frames) >= 25)
        before = angles(run.frames[-1])
        edit(SETTINGS, BAY_BREAKER, open=True)  # the graph, not the source (seconds, in rdflib)
        edited = utcnow()
        # The flow goes round the other way within a POLL and a refresh (measured: 0.25 s).
        await run.until(lambda: np.max(np.abs(angles(run.frames[-1]) - before)) > 0.1, timeout=10)
        assert run.frames[-1].timestamp - edited < timedelta(seconds=2)


async def test_a_store_that_cannot_be_read_does_not_end_the_stream(monkeypatch):
    calls = {"n": 0}

    def flaky(self):
        calls["n"] += 1
        raise ConnectionError("the store is down")

    monkeypatch.setattr(follow_module.Controller, "changes", flaky)
    async with Run(make(poll=0.05)) as run:
        await run.until(lambda: calls["n"] >= 3)
        count = len(run.frames)
        await run.until(lambda: len(run.frames) > count + 10)  # still frames


def test_a_script_reads_a_bounded_window():
    frames = list(islice(make().read(end=utcnow() + timedelta(seconds=120)), 25))  # starting takes seconds
    assert len(frames) == 25 and all(f.header.data_rate == 50.0 for f in frames)


async def test_a_grid_that_cannot_be_loaded_ends_the_stream_with_the_reason(tmp_path):
    with pytest.raises(RuntimeError, match="CGMES"):
        async for _ in RtsimFromCimSource(graph=CimSettings(cim_path=tmp_path)).aread():
            pass


@needs_profiles
async def test_a_repository_a_script_hands_over_is_simulated_and_its_edits_followed():
    # A store of the script's own, filled by its owner: no version stamp, so edits are looked for
    # every couple of seconds. The repository cannot leave the process: it is followed from a thread.
    from lazycim import CIMRepository
    from lazycim.demo import CIM100

    from pswamp_core.cim import LocalStore, Store
    from pswamp_core.cim.grid import NAMESPACE_ALIASES

    theirs = Store(SETTINGS, LocalStore("theirs"))
    theirs.fill()
    theirs.backend.update("DROP SILENT GRAPH <urn:pswamp:meta>")

    def repository(**layout) -> CIMRepository:
        return CIMRepository(theirs.backend, default_namespace=CIM100, namespace_aliases=NAMESPACE_ALIASES, **layout)

    async with Run(RtsimFromCimSource(repo=repository(graphs="discover"))) as run:
        await run.until(lambda: len(run.frames) >= 25)
        assert "rtsim-follow" not in {p.name for p in multiprocessing.active_children()}
        before = angles(run.frames[-1])
        script = repository(graphs=theirs.layout)  # the script's second repository; no stamp moves
        script.from_mRID(BAY_BREAKER).open = True
        script.commit()
        assert theirs.version() == 0
        await run.until(lambda: np.max(np.abs(angles(run.frames[-1]) - before)) > 0.1, timeout=15)
