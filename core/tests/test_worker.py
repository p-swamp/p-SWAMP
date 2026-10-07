"""The worker's configuration."""

from __future__ import annotations

import pytest
from support import install_modules, write_pipeline

from pswamp_core import worker

PIPELINE_FILE = """
app = "app"
modules = ["counter", "halver"]

[[sources]]
name = "rec"
module = "list-source"
"""


@pytest.fixture
def pipeline_file(monkeypatch, tmp_path):
    install_modules(
        monkeypatch, counter="test_pipeline:FrameCounter", halver="test_modules:Halver", **{"list-source": "support:ListSource"}
    )
    return write_pipeline(tmp_path / "app.toml", PIPELINE_FILE)


def test_pipelines_are_named_by_file(pipeline_file, monkeypatch):
    (pipeline,) = worker.load_pipelines(str(pipeline_file))
    assert pipeline.app == "app" and [m.name for m in pipeline.modules] == ["counter", "halver"]
    # Relative to the working directory, as the workers in compose and k8s name them.
    monkeypatch.chdir(pipeline_file.parent)
    assert [p.app for p in worker.load_pipelines(" app.toml, ")] == ["app"]
    for bad in ("test_pipeline:PIPELINE", "app", "missing.toml"):
        with pytest.raises(ValueError):
            worker.load_pipelines(bad)


def test_a_worker_needs_a_broker_and_something_to_host(pipeline_file, monkeypatch, capsys):
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    assert worker.main() == 2
    assert "server hosts the modules" in capsys.readouterr().err
    monkeypatch.setenv("PSWAMP_TRANSPORT", "kafka:pswamp_core.transport.kafka:KafkaTransport")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:1")
    monkeypatch.setenv("PSWAMP_WORKER_PIPELINES", str(pipeline_file))
    monkeypatch.setenv("PSWAMP_WORKER_MODULES", "nothing-by-this-name")
    assert worker.main() == 2
    assert "name no module to host" in capsys.readouterr().err
    monkeypatch.setenv("PSWAMP_WORKER_PIPELINES", "nowhere.toml")
    assert worker.main() == 2
    assert "no such pipeline file" in capsys.readouterr().err
