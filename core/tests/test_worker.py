"""The worker's configuration."""

from __future__ import annotations

import pytest

from pswamp_core import worker


def test_pipelines_are_named_by_reference():
    (pipeline,) = worker.load_pipelines("test_pipeline:PIPELINE_FOR_WORKER")
    assert pipeline.app == "app"
    for bad in ("test_pipeline", "test_pipeline:gateway"):
        with pytest.raises(ValueError):
            worker.load_pipelines(bad)


def test_a_worker_needs_a_broker_and_something_to_host(monkeypatch, capsys):
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    assert worker.main() == 2
    assert "server hosts the modules" in capsys.readouterr().err
    monkeypatch.setenv("PSWAMP_TRANSPORT", "kafka:pswamp_core.transport.kafka:KafkaTransport")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:1")
    monkeypatch.setenv("PSWAMP_WORKER_PIPELINES", "test_pipeline:PIPELINE_FOR_WORKER")
    monkeypatch.setenv("PSWAMP_WORKER_MODULES", "nothing-by-this-name")
    assert worker.main() == 2
