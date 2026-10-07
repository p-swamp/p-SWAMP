"""Pipeline files: ``Pipeline.load`` reads ``pipelines/<app>.toml``.

The modules are faked as installed (``support.install_modules``), so these
tests need no module project; the real file, pipelines/pmu-test-streamer.toml,
is loaded in app/server-python/tests/test_pipeline_files.py."""

from __future__ import annotations

import pytest
from support import ListClient, Measurement, install_modules, write_pipeline
from test_modules import HalveCommand

from pswamp_core.modules import Module
from pswamp_core.pipeline import Pipeline
from pswamp_core.pipeline_config import ConfiguredGateway, PipelineConfigError, load_pipeline, main
from pswamp_models.pmu import PmuFrame

PIPELINE = """
app = "app"
modules = ["counter", "halver"]

[[sources]]
name = "rec"
client = "support:ListClient"

[[sources]]
name = "tick"
client = "support:TickingClient"

[enrich]
cim_reference = "cim-1"
"""


class ReadsMeasurement(Module):
    """Reads a class no source serves and no module emits."""

    name = "reads-measurement"
    inputs = (Measurement,)

    def process(self, message: Measurement) -> None:
        return None


class AlsoHalves(Module):
    """Takes the command ``halver`` takes."""

    name = "also-halves"
    commands = (HalveCommand,)

    def handle(self, command: HalveCommand) -> None:
        return None


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    install_modules(
        monkeypatch,
        counter="test_pipeline:FrameCounter",
        halver="test_modules:Halver",
        **{
            "reads-measurement": "test_pipeline_config:ReadsMeasurement",
            "also-halves": "test_pipeline_config:AlsoHalves",
            "misnamed": "test_modules:Halver",
        },
    )
    for variable in ("APP_DATA_CLIENTS", "APP_CIM_REFERENCE"):
        monkeypatch.delenv(variable, raising=False)


def load(tmp_path, text: str = PIPELINE) -> Pipeline:
    return Pipeline.load(write_pipeline(tmp_path / "app.toml", text))


async def test_a_file_declares_the_app_its_modules_and_its_sources(tmp_path):
    pipeline = load(tmp_path)
    assert pipeline.app == "app"
    assert [m.name for m in pipeline.modules] == ["counter", "halver"]
    assert pipeline.source_models == (PmuFrame,)
    gateway = pipeline.gateway()
    assert gateway.sources == ["rec", "tick"] and gateway.source == "rec"  # the first is the default
    assert isinstance(gateway.active, ListClient)
    first = await anext(await gateway.consume())
    assert first.header.cimReferenceId == "cim-1"
    assert load_pipeline(tmp_path / "app.toml").app == "app"


async def test_the_environment_overrides_the_sources_and_the_cim_reference(tmp_path, monkeypatch):
    pipeline = load(tmp_path)
    assert isinstance(pipeline.gateway, ConfiguredGateway)
    assert (pipeline.gateway.clients_variable, pipeline.gateway.cim_variable) == ("APP_DATA_CLIENTS", "APP_CIM_REFERENCE")
    monkeypatch.setenv("APP_DATA_CLIENTS", "other:support:TickingClient,again:support:ListClient")
    monkeypatch.setenv("APP_CIM_REFERENCE", "none")
    gateway = pipeline.gateway()
    assert gateway.sources == ["other", "again"] and gateway.live
    gateway.switch("again")
    assert (await anext(await gateway.consume())).header.cimReferenceId is None


def test_no_enrich_table_means_no_reference(tmp_path):
    text = PIPELINE.split("[enrich]")[0]
    assert load(tmp_path, text).gateway().enrichers == ()


def test_an_unknown_module_lists_the_installed_ones(tmp_path):
    with pytest.raises(PipelineConfigError, match=r"app.toml: .*'nope'.* installed: also-halves, counter, halver"):
        load(tmp_path, PIPELINE.replace('"halver"', '"nope"'))


def test_an_entry_point_must_be_named_after_its_module(tmp_path):
    with pytest.raises(PipelineConfigError, match="is named 'halver'"):
        load(tmp_path, PIPELINE.replace('"halver"', '"misnamed"'))


def test_every_input_needs_a_producer(tmp_path):
    with pytest.raises(PipelineConfigError, match="reads-measurement reads Measurement, which nothing in the pipeline produces"):
        load(tmp_path, PIPELINE.replace('"halver"', '"reads-measurement"'))


def test_the_existing_checks_still_apply(tmp_path):
    with pytest.raises(PipelineConfigError, match="Halver and AlsoHalves both take HalveCommand"):
        load(tmp_path, PIPELINE.replace('"counter"', '"also-halves"'))
    with pytest.raises(PipelineConfigError, match="module halver listed twice"):
        load(tmp_path, PIPELINE.replace('"counter"', '"halver"'))


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        (PIPELINE.replace('app = "app"', 'app = "App 1"'), "app: String should match"),
        (PIPELINE.replace("[enrich]", "[enrich]\ncolour = 1"), "enrich.colour: Extra inputs"),
        (PIPELINE.replace('"support:ListClient"', '"support.ListClient"'), "sources.0.client"),
        (PIPELINE.replace('"support:ListClient"', '"support:Measurement"'), "is not a DataClient"),
        (PIPELINE.replace('name = "tick"', 'name = "rec"'), "source rec listed twice"),
        ('app = "app"\n', "sources: Field required"),
        ("app = ", "app.toml: "),
    ],
)
def test_a_bad_file_says_which_and_why(tmp_path, text, complaint):
    with pytest.raises(PipelineConfigError, match="app.toml") as raised:
        load(tmp_path, text)
    assert complaint in str(raised.value)


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(PipelineConfigError, match="no such pipeline file"):
        Pipeline.load(tmp_path / "nowhere.toml")


def test_the_command_line_lists_modules_and_validates_files(tmp_path, capsys):
    good = write_pipeline(tmp_path / "app.toml", PIPELINE)
    bad = write_pipeline(tmp_path / "bad.toml", PIPELINE.replace('"halver"', '"reads-measurement"'))
    assert main(["validate", str(good)]) == 0
    assert "app app, sources rec, tick, modules counter, halver" in capsys.readouterr().out
    assert main(["validate", str(good), str(bad)]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert main(["modules"]) == 1  # "misnamed" does not resolve
    out = capsys.readouterr().out
    assert "counter" in out and "reads:    PmuFrame" in out and "commands: HalveCommand" in out


def test_a_byte_order_mark_is_not_an_error(tmp_path):
    path = tmp_path / "app.toml"
    path.write_bytes(b"\xef\xbb\xbf" + PIPELINE.encode("utf-8"))
    assert Pipeline.load(path).app == "app"
