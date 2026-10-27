"""A module reads the CIM graph through a repository of its own, and every PMU frame is tied to the graph."""

from __future__ import annotations

import asyncio

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
