"""The Kafka transport. The suite needs a broker:

    docker compose up -d kafka
    KAFKA_TEST_BOOTSTRAP_SERVERS=127.0.0.1:19092 uv run pswamp test server -k kafka

and is skipped without one.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys

import pytest
from support import Measurement, measurement, take
from transport_suite import TransportSuite

from pswamp_core.settings import MissingSettingError
from pswamp_core.subscription import Overflow
from pswamp_core.transport import transport_from_env
from pswamp_core.transport.kafka import KafkaTransport
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.player import PauseCommand, PlayCommand

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


@pytest.mark.skipif(not BOOTSTRAP, reason="KAFKA_TEST_BOOTSTRAP_SERVERS is not set")
async def test_a_reopened_consumer_resumes_the_command_topics_and_not_the_data(app):
    receiver, sender = KafkaTransport("receiver", BOOTSTRAP), KafkaTransport("sender", BOOTSTRAP)
    try:
        with receiver.subscribe(PauseCommand, Measurement, app=app, overflow=Overflow.GROW) as feed:
            await feed.ready(20)
            await cancel_and_wait(receiver._consumer_task)  # its broker went away, as far as it knows
            command = PauseCommand()
            await sender.publish(command, app=app, key="k")  # meanwhile
            await sender.publish(measurement(1), app=app, key="k")
            receiver._consumer_task = asyncio.create_task(receiver._consume())  # reopened
            await feed.ready(20)
            ((key, got),) = await take(feed, 1, timeout=20)
            assert (key, type(got), got.request_id) == ("k", PauseCommand, command.request_id)
            await asyncio.sleep(1)
            assert feed.get_nowait() is None  # the frame from meanwhile is not read back
    finally:
        await receiver.close()
        await sender.close()


@pytest.mark.skipif(not BOOTSTRAP, reason="KAFKA_TEST_BOOTSTRAP_SERVERS is not set")
async def test_commands_from_meanwhile_arrive_in_the_order_sent_across_their_topics(app):
    receiver, sender = KafkaTransport("receiver", BOOTSTRAP), KafkaTransport("sender", BOOTSTRAP)
    try:
        with receiver.subscribe(PauseCommand, PlayCommand, app=app, overflow=Overflow.GROW) as feed:
            await feed.ready(20)
            await cancel_and_wait(receiver._consumer_task)
            sent = [PauseCommand(), PlayCommand(), PauseCommand(), PlayCommand()]  # one topic per class
            for command in sent:
                await sender.publish(command, app=app, key="k")
            receiver._consumer_task = asyncio.create_task(receiver._consume())  # reopened: all four in one fetch
            await feed.ready(20)
            got = await take(feed, len(sent), timeout=20)
            assert [message.request_id for _, message in got] == [command.request_id for command in sent]
    finally:
        await receiver.close()
        await sender.close()


@pytest.mark.skipif(not BOOTSTRAP, reason="KAFKA_TEST_BOOTSTRAP_SERVERS is not set")
async def test_topics_the_broker_lost_are_made_again_both_ways(app):
    from aiokafka.admin import AIOKafkaAdminClient

    receiver, sender = KafkaTransport("receiver", BOOTSTRAP), KafkaTransport("sender", BOOTSTRAP)
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    try:
        with receiver.subscribe(PauseCommand, app=app, overflow=Overflow.GROW) as feed:
            await feed.ready(20)
            await sender.publish(PauseCommand(), app=app, key="k")
            await take(feed, 1, timeout=20)
            await admin.delete_topics([receiver.topic(PauseCommand, app)])  # a new broker, with no volume
            await asyncio.sleep(1)
            command = PauseCommand()

            async def until_received():
                while True:
                    with contextlib.suppress(Exception):  # the first tries fail: the topic is gone
                        await sender.publish(command, app=app, key="k")
                    got = feed.get_nowait()
                    if got is not None and got[1].request_id == command.request_id:
                        return
                    await asyncio.sleep(0.5)

            await asyncio.wait_for(until_received(), 60)
    finally:
        await admin.close()
        await receiver.close()
        await sender.close()


@pytest.mark.skipif(not BOOTSTRAP, reason="KAFKA_TEST_BOOTSTRAP_SERVERS is not set")
async def test_a_consumer_reopened_on_a_new_broker_makes_its_topics_again(app):
    from aiokafka.admin import AIOKafkaAdminClient

    transport = KafkaTransport("receiver", BOOTSTRAP)
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    try:
        with transport.subscribe(PauseCommand, app=app, overflow=Overflow.GROW) as feed:
            await feed.ready(20)
            await cancel_and_wait(transport._consumer_task)  # the broker went away...
            await admin.delete_topics([transport.topic(PauseCommand, app)])  # ...and came back with nothing
            await asyncio.sleep(1)
            transport._consumer_task = asyncio.create_task(transport._consume())  # reopened, as on a connection error
            await feed.ready(15)  # it made the topic again, so its offsets answer
            assert transport.topic(PauseCommand, app) in await admin.list_topics()
    finally:
        await admin.close()
        await transport.close()
