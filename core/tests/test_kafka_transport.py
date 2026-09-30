"""The Kafka transport. The suite needs a broker:

    docker compose up -d kafka
    KAFKA_TEST_BOOTSTRAP_SERVERS=127.0.0.1:19092 ./scripts/run-python-server-tests.sh -k kafka

and is skipped without one.
"""

from __future__ import annotations

import os
import sys

import pytest
from support import Measurement
from transport_suite import TransportSuite

from pswamp_core.settings import MissingSettingError
from pswamp_core.transport import transport_from_env
from pswamp_core.transport.kafka import KafkaTransport

BOOTSTRAP = os.environ.get("KAFKA_TEST_BOOTSTRAP_SERVERS", "")


def test_constructing_needs_no_broker_and_no_aiokafka():
    before = "aiokafka" in sys.modules
    transport = KafkaTransport("k", "localhost:9092")
    assert transport.topic(Measurement, "app") == "app.measurement"
    assert ("aiokafka" in sys.modules) == before


def test_it_is_configured_from_its_env_block(monkeypatch):
    monkeypatch.setenv("T", "kafka:pswamp_core.transport.kafka:KafkaTransport")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "a:9092, b:9092")
    monkeypatch.setenv("KAFKA_REPLICATION_FACTOR", "3")
    transport = transport_from_env("T")
    assert isinstance(transport, KafkaTransport)
    assert transport.bootstrap_servers == ["a:9092", "b:9092"] and transport.replication_factor == 3
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS")
    with pytest.raises(MissingSettingError):
        transport_from_env("T")


@pytest.mark.skipif(not BOOTSTRAP, reason="KAFKA_TEST_BOOTSTRAP_SERVERS is not set")
class TestKafkaTransport(TransportSuite):
    @pytest.fixture
    async def transport(self):
        transport = KafkaTransport("kafka", BOOTSTRAP)
        yield transport
        await transport.close()
