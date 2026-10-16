"""Pipeline files: ``Pipeline.load`` reads ``pipelines/<app>.toml``.

The modules are faked as installed (``support.install_modules``), so these
tests need no module project; the real file, pipelines/pmu-test-streamer.toml,
is loaded in app/server-python/tests/test_pipeline_files.py."""

from __future__ import annotations

import pytest
from support import ListSource, Measurement, install_modules, write_pipeline
from test_modules import HalveCommand

from pswamp_core.modules import Module
from pswamp_core.pipeline import Pipeline
from pswamp_core.pipeline_config import ConfiguredSources, PipelineConfigError, load_pipeline, main, resolve_module
from pswamp_models.pmu import PmuFrame

PIPELINE = """
app = "app"
modules = ["counter", "halver"]

[[sources]]
name = "rec"
module = "list-source"

[[sources]]
name = "tick"
module = "ticking-source"

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
            "list-source": "support:ListSource",
            "ticking-source": "support:TickingSource",
            "reads-measurement": "test_pipeline_config:ReadsMeasurement",
            "also-halves": "test_pipeline_config:AlsoHalves",
            "misnamed": "test_modules:Halver",
        },
    )
    for variable in ("APP_SOURCES", "APP_DATA_CLIENTS", "APP_CIM_REFERENCE"):
        monkeypatch.delenv(variable, raising=False)


def load(tmp_path, text: str = PIPELINE) -> Pipeline:
    return Pipeline.load(write_pipeline(tmp_path / "app.toml", text))


async def test_a_file_declares_the_app_its_modules_and_its_sources(tmp_path):
    pipeline = load(tmp_path)
    assert pipeline.app == "app"
    assert [m.name for m in pipeline.modules] == ["counter", "halver"]
    assert pipeline.source_models == (PmuFrame,)
    sources = pipeline.sources()
    assert sources.sources == ["rec", "tick"] and sources.source == "rec"  # the first is the default
    assert isinstance(sources.active, ListSource)
    first = await anext(await sources.consume())
    assert first.header.cimReferenceId == "cim-1"
    assert load_pipeline(tmp_path / "app.toml").app == "app"


async def test_the_environment_overrides_the_sources_and_the_cim_reference(tmp_path, monkeypatch):
    pipeline = load(tmp_path)
    assert isinstance(pipeline.sources, ConfiguredSources)
    assert (pipeline.sources.sources_variable, pipeline.sources.cim_variable) == ("APP_SOURCES", "APP_CIM_REFERENCE")
    monkeypatch.setenv("APP_SOURCES", "other:ticking-source,again:list-source")
    monkeypatch.setenv("APP_CIM_REFERENCE", "none")
    sources = pipeline.sources()
    assert sources.sources == ["other", "again"] and sources.live
    sources.switch("again")
    assert (await anext(await sources.consume())).header.cimReferenceId is None


def test_the_retired_data_clients_variable_is_an_error_naming_its_replacement(tmp_path, monkeypatch):
    pipeline = load(tmp_path)
    monkeypatch.setenv("APP_DATA_CLIENTS", "rec:support:ListClient")
    with pytest.raises(PipelineConfigError, match=r"APP_DATA_CLIENTS is no longer read.*APP_SOURCES=name:entry-point"):
        pipeline.sources()
    with pytest.raises(PipelineConfigError, match="APP_SOURCES=name:entry-point"):
        load(tmp_path)  # a server fails to start rather than ignore it


def test_a_malformed_sources_variable_is_refused(tmp_path, monkeypatch):
    pipeline = load(tmp_path)
    for bad in ("rec", "rec:", ":list-source", "rec:list:source"):
        monkeypatch.setenv("APP_SOURCES", bad)
        with pytest.raises(PipelineConfigError, match="is not name:entry-point"):
            pipeline.sources()
    monkeypatch.setenv("APP_SOURCES", "rec:halver")
    with pytest.raises(PipelineConfigError, match="'halver' is an analysis module, not a source"):
        pipeline.sources()
    monkeypatch.setenv("APP_SOURCES", "rec:nope")
    with pytest.raises(PipelineConfigError, match="no module named 'nope'"):
        pipeline.sources()


def test_no_enrich_table_means_no_reference(tmp_path):
    text = PIPELINE.split("[enrich]")[0]
    assert load(tmp_path, text).sources().enrichers == ()


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
        (PIPELINE.replace('"list-source"', '"List Source"'), "sources.0.module"),
        (PIPELINE.replace('"list-source"', '"halver"'), "is an analysis module, not a source"),
        (PIPELINE.replace('module = "list-source"', 'client = "support:ListSource"'), "sources.0.module: Field required"),
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


def test_a_source_is_listed_with_its_kind_and_is_not_an_analysis_module(monkeypatch, capsys):
    install_modules(
        monkeypatch,
        **{"list-source": "support:ListSource", "ticking-source": "support:TickingSource", "halver": "test_modules:Halver"},
    )
    assert main(["modules"]) == 0
    out = capsys.readouterr().out
    assert "kind:     source (history, playable)" in out
    assert "kind:     source (live, not playable)" in out
    assert "kind:     module" in out
    with pytest.raises(PipelineConfigError, match="is a source"):
        resolve_module("list-source")
