"""A module reads the CIM graph through a repository of its own, and every PMU frame is tied to the graph."""

from __future__ import annotations

import asyncio
import time
from typing import Literal

import pytest

pytest.importorskip("lazycim")

from support import Measurement, Number, NumberResult, at, measurement, take  # noqa: E402

from pswamp_core.cim import SAMPLE_GRID, CimSettings, ReadOnlyRepository, analog_index, stage  # noqa: E402
from pswamp_core.cim.enrich import CimEnricher, column_analogs  # noqa: E402
from pswamp_core.host import ModuleHost  # noqa: E402
from pswamp_core.modules import Module  # noqa: E402
from pswamp_core.subscription import Overflow  # noqa: E402
from pswamp_core.transport import InMemoryTransport  # noqa: E402
from pswamp_core.util.tasks import cancel_and_wait  # noqa: E402
from pswamp_models.common import Command  # noqa: E402
from pswamp_models.pmu import PmuFrame, PmuHeader  # noqa: E402

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
INDEX = {
    "PMU_Beta_400_V": "beta-v",
    "PMU_Beta_400_F": "beta-f",
    "PMU_Gamma_132_V": "gamma132-v",
    "PMU_Gamma_400_V": "gamma400-v",
    "PMU_Alpha_400_I_Alpha-Beta_400_kV_line": "alpha-i-ab",
}


@pytest.fixture
def grid_env(monkeypatch):
    monkeypatch.setenv("PSWAMP_CIM_PATH", str(SAMPLE_GRID))
    if not stage(SETTINGS).writable:
        pytest.skip("the CGMES vocabularies are not available to LazyCIM")


def header(stations, channels, measurements, analog=None):
    return PmuHeader(
        station=stations, channel=channels, measurement=measurements, units=["x"] * len(stations), data_rate=25.0, analog=analog
    )


def pmu(h: PmuHeader) -> PmuFrame:
    return PmuFrame(timestamp=at(0), mRID="s", header=h, values=[1.0] * h.n_columns)


class CountsAnalogs(Module):
    name = "counts-analogs"
    cim = True
    inputs = (Measurement,)
    outputs = (NumberResult,)

    def process(self, message):
        return Number(value=len(analog_index(self.cim_repo)))


def test_a_column_finds_its_analog_by_name():
    h = header(
        ["Beta", "Beta", "Beta", "Gamma", "Alpha", "Delta"],
        ["V", "V", "f", "V", "I_Alpha-Beta 400 kV line", "V"],
        ["V_Magnitude", "V_Angle", "f", "V_Magnitude", "I_Magnitude", "V_Magnitude"],
    )
    # A phasor's two columns share an Analog; Gamma has two levels, so it is ambiguous; Delta is no station.
    assert column_analogs(h, INDEX) == ["beta-v", "beta-v", "beta-f", None, "alpha-i-ab", None]
    assert column_analogs(h, INDEX, {"Gamma": "Gamma_400"})[3] == "gamma400-v"


def test_a_frequency_derivative_shares_the_frequency_s_analog():
    assert column_analogs(header(["Beta"], ["f"], ["df"]), INDEX) == ["beta-f"]


async def test_frames_are_tied_to_the_grid_once_it_is_read(grid_env):
    enricher = CimEnricher(SETTINGS, stations={})
    untouched = pmu(header(["Beta"], ["V"], ["V_Magnitude"]))
    assert enricher.enrich(untouched) is untouched  # not read yet: frames flow as they are
    await enricher.ready()
    first, second = enricher.enrich(untouched), enricher.enrich(pmu(untouched.header))
    assert first.header.cimReferenceId == "3f5e0000-0000-4000-8000-000000000001"
    assert first.header.analog == [enricher.index["PMU_Beta_400_V"]]
    assert first.header is second.header  # once per layout


async def test_a_frame_that_carries_its_analogs_keeps_them(grid_env):
    enricher = CimEnricher(SETTINGS, stations={})
    await enricher.ready()
    linked = pmu(header(["Beta"], ["V"], ["V_Magnitude"], analog=["mine"]))
    assert enricher.enrich(linked).header.analog == ["mine"]


async def test_a_grid_that_cannot_be_read_leaves_frames_alone(tmp_path):
    enricher = CimEnricher(CimSettings(cim_path=tmp_path), stations={})
    await enricher.ready()
    original = pmu(header(["Beta"], ["V"], ["V_Magnitude"]))
    assert enricher.enrich(original).header.cimReferenceId is None


def test_a_module_reads_the_graph_through_a_repository_of_its_own(grid_env):
    one, two = CountsAnalogs(), CountsAnalogs()
    assert one.run_one(measurement(1)).result.value == 14
    assert isinstance(one.cim_repo, ReadOnlyRepository) and one.cim_repo is not two.cim_repo


def test_a_module_that_does_not_ask_has_no_repository():
    class Plain(Module):
        name = "plain"
        inputs = (Measurement,)
        outputs = (NumberResult,)

        def process(self, message):
            return Number(value=0)

    with pytest.raises(AttributeError, match="cim = True"):
        Plain().cim_repo  # noqa: B018


async def test_a_host_connects_the_repository_before_setup(grid_env):
    seen = []

    class Checks(CountsAnalogs):
        name = "checks"

        async def setup(self):
            seen.append(self._cim_repo is not None)

    broker = InMemoryTransport()
    host = ModuleHost(Checks, broker, app="a")
    task = asyncio.create_task(host.serve())
    for _ in range(5):
        await asyncio.sleep(0)
    with broker.subscribe(NumberResult, app="a", overflow=Overflow.GROW) as results:
        await broker.publish(measurement(1), app="a", key="k")
        (_, result), = await take(results, 1, timeout=60)
    assert seen == [True] and result.result.value == 14
    await cancel_and_wait(task)


# The core keeps a module's repository up to date: the module has no code for it.

COUPLER = "3f5e0000-0000-4000-8000-000000000034"  # Beta's bus coupler, closed in the sample grid


class SetTo(Command):
    version: Literal["v1"] = "v1"
    value: float


class ReadsTheCoupler(Module):
    """Reads one switch of the grid per input or command, and counts what ``cim_changed`` was told."""

    name = "reads-the-coupler"
    cim = True
    inputs = (Measurement,)
    outputs = (NumberResult,)
    commands = (SetTo,)

    def __init__(self):
        super().__init__()
        self.changes = 0

    def cim_changed(self):
        self.changes += 1

    def _coupler(self):
        return Number(value=1.0 if self.cim_repo.from_mRID(COUPLER).open else 0.0)

    def process(self, message):
        return self._coupler()

    def handle(self, command):
        return self._coupler()


@pytest.fixture
def fast_watch(grid_env, monkeypatch):
    """Watches that poll every 10 ms, and the grid as loaded again afterwards."""
    from pswamp_core.cim import testing, watch

    watch.close_watches()
    monkeypatch.setattr(watch, "POLL", 0.01)
    yield
    testing.reset(SETTINGS)
    watch.close_watches()


def wait_stale(module, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not module._cim_fresh.stale():
        assert time.monotonic() < deadline, "the watch never saw the edit"
        time.sleep(0.01)


def test_a_module_reads_an_edit_with_no_code_of_its_own(fast_watch):
    from pswamp_core.cim import testing

    module = ReadsTheCoupler()
    assert module.run_one(measurement(1)).result.value == 0.0
    testing.edit(SETTINGS, COUPLER, open=True)
    wait_stale(module)
    assert module.run_one(measurement(2)).result.value == 1.0
    assert module.changes == 1
    module.run(measurement(3))
    assert module.changes == 1  # nothing changed since: not told again


def test_an_unchanged_graph_costs_a_module_no_query(fast_watch):
    module = ReadsTheCoupler()
    module.run(measurement(1))
    time.sleep(0.05)  # the watch polls meanwhile, in its own thread
    with module.cim_repo.measure() as work:
        for i in range(20):
            module.run(measurement(i))
    assert work.queries == 0 and module.changes == 0


def test_a_command_reads_the_edit_too(fast_watch):
    from pswamp_core.cim import testing

    module = ReadsTheCoupler()
    assert module.run_command(SetTo(value=0))[0].result.value == 0.0
    testing.edit(SETTINGS, COUPLER, open=True)
    wait_stale(module)
    assert module.run_command(SetTo(value=0))[0].result.value == 1.0 and module.changes == 1


async def test_a_hosted_module_reads_the_edit_on_its_next_input_and_command(fast_watch):
    from pswamp_core.cim import testing

    instances: list[ReadsTheCoupler] = []

    def build():
        instances.append(ReadsTheCoupler())
        return instances[-1]

    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(build, broker, app="a").serve())
    for _ in range(5):
        await asyncio.sleep(0)
    with broker.subscribe(NumberResult, app="a", overflow=Overflow.GROW) as results:
        await broker.publish(measurement(1), app="a", key="k")
        (_, before), = await take(results, 1, timeout=60)
        (module,) = instances[1:]  # the first is the host's template
        await asyncio.to_thread(testing.edit, SETTINGS, COUPLER, open=True)
        await asyncio.to_thread(wait_stale, module)
        await broker.publish(measurement(2), app="a", key="k")
        await broker.publish(SetTo(value=0), app="a", key="k")
        (_, after), (_, answer) = await take(results, 2, timeout=60)
    assert before.result.value == 0.0 and after.result.value == 1.0 and answer.result.value == 1.0
    assert module.changes == 1
    await cancel_and_wait(task)


def test_a_watch_outlives_a_store_that_fails_for_a_while(grid_env, monkeypatch):
    from pswamp_core.cim import LocalStore, Store
    from pswamp_core.cim import watch as watching

    store = Store(SETTINGS, LocalStore())
    store.fill()
    monkeypatch.setattr(watching, "POLL", 0.01)
    watch = watching.GraphWatch.of(store)
    real = store.backend.execute

    def down(query):
        raise ConnectionError("down")

    try:
        store.backend.execute = down
        time.sleep(0.05)
        assert watch.generation == 0 and watch._thread.is_alive()
        store.backend.execute = real
        store.backend.update(  # as a write would: the stamp moves on
            "DELETE WHERE { GRAPH <urn:pswamp:meta> { ?s ?p ?o } } ; "
            "INSERT DATA { GRAPH <urn:pswamp:meta> { <urn:pswamp:cim> <urn:pswamp:version> 99 } }"
        )
        deadline = time.monotonic() + 5
        while watch.generation == 0:
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        store.backend.execute = real
        watching.close_watches()
