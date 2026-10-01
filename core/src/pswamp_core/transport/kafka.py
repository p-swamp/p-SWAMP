# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``KafkaTransport``: the transport over a Kafka broker.

    PSWAMP_TRANSPORT=kafka:pswamp_core.transport.kafka:KafkaTransport
    KAFKA_BOOTSTRAP_SERVERS=kafka:9092

- **Topics.** ``<app>.<model.topic>``, created on first use with one partition
  (so a topic stays in order) and bounded retention (``LIVE_TOPIC_CONFIGS``).
  Every topic is a live hop that nobody reads back; the broker's default of a
  week let a fast replay fill a laptop's disk in minutes.
- **Keys.** The run's key is the record key; the value is the message's JSON.
  A record that does not validate is logged and dropped.
- **One consumer per process**, assigned every topic the process listens to
  and re-assigned when a new one is added, keeping its position on the others.
  (One consumer per topic, some fifty in the server, starved each other.)
  No consumer group and no committed offsets: a process that restarts wants
  what is said from now on, not a backlog. A new topic is read from its end.
- **Backpressure.** ``publish`` waits for the broker's acknowledgement, so a
  slow broker backs up into the caller's ``Outbox``, which drops old data.

Needs the ``kafka`` extra. aiokafka is imported where it is used, so naming
this class costs nothing without it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ..log import get_logger
from ..messages.data_model import stamp_sent_at
from ..settings import EnvSetting
from . import Transport

if TYPE_CHECKING:
    from ..messages.data_model import DataModel

__all__ = ["LIVE_TOPIC_CONFIGS", "KafkaTransport"]

logger = get_logger("pswamp_core.transport.kafka")

#: Every topic keeps about a minute, or 256 MB, whichever comes first. The
#: broker applies it every log.retention.check.interval.ms (five minutes by
#: default), so the compose and k8s brokers set that to 10 s.
LIVE_TOPIC_CONFIGS: dict[str, str] = {
    "retention.ms": "60000",
    "retention.bytes": str(256 * 1024 * 1024),
    "segment.ms": "10000",
    "segment.bytes": str(32 * 1024 * 1024),
    "file.delete.delay.ms": "1000",
}

_TOPIC_ALREADY_EXISTS = 36
#: How long one fetch waits, and so how soon a new topic is taken on.
_POLL_MS = 200
_RECONNECT_DELAY, _MAX_RECONNECT_DELAY = 1.0, 30.0


class KafkaTransport(Transport):
    """Keyed publish/subscribe over a Kafka broker. See the module docstring."""

    env_settings = (
        EnvSetting("BOOTSTRAP_SERVERS", "Broker addresses, e.g. kafka:9092", required=True, kind="list"),
        EnvSetting("REPLICATION_FACTOR", "For the topics this transport creates", default="1", kind="int"),
    )

    def __init__(
        self,
        name: str = "kafka",
        bootstrap_servers: str | Sequence[str] = "localhost:9092",
        *,
        replication_factor: int = 1,
    ) -> None:
        super().__init__(name)
        self.bootstrap_servers = bootstrap_servers if isinstance(bootstrap_servers, str) else list(bootstrap_servers)
        self.replication_factor = replication_factor
        self._producer: Any | None = None
        self._admin: Any | None = None
        self._open_lock = asyncio.Lock()
        self._created: set[str] = set()
        #: Topics listened to but not yet assigned to the consumer.
        self._unassigned: set[str] = set()
        self._consumer_task: asyncio.Task | None = None

    async def open(self) -> None:
        async with self._open_lock:
            if self._producer is not None:
                return
            from aiokafka import AIOKafkaProducer

            producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap_servers, request_timeout_ms=10_000)
            await producer.start()
            self._producer = producer
            logger.info("%s: connected to %s", self.name, self.bootstrap_servers)

    async def close(self) -> None:
        task, self._consumer_task = self._consumer_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await super().close()
        producer, self._producer = self._producer, None
        admin, self._admin = self._admin, None
        if producer is not None:
            await producer.stop()
        if admin is not None:
            await admin.close()

    async def publish(self, message: DataModel, *, app: str, key: str) -> None:
        if self._producer is None:
            await self.open()
        topic = self.topic(type(message), app)
        await self._create(topic)
        await self._producer.send_and_wait(topic, value=message.model_dump_json().encode(), key=key.encode())

    async def _create(self, topic: str) -> None:
        """Create ``topic`` if the broker lacks it. A refusal is logged and left
        to the produce or consume that follows."""
        if topic in self._created:
            return
        from aiokafka.admin import AIOKafkaAdminClient, NewTopic
        from aiokafka.errors import TopicAlreadyExistsError

        if self._admin is None:
            self._admin = AIOKafkaAdminClient(bootstrap_servers=self.bootstrap_servers)
            await self._admin.start()
        new = NewTopic(topic, num_partitions=1, replication_factor=self.replication_factor, topic_configs=LIVE_TOPIC_CONFIGS)
        try:
            response = await self._admin.create_topics([new])
        except TopicAlreadyExistsError:
            self._created.add(topic)
            return
        except Exception as error:
            logger.warning("%s: could not create topic %s: %s", self.name, topic, error)
            return
        # aiokafka reports per topic: (name, error code, message).
        for name, code, text in getattr(response, "topic_errors", []):
            if code not in (0, _TOPIC_ALREADY_EXISTS):
                logger.warning("%s: could not create topic %s: %s", self.name, name, text)
                return
        self._created.add(topic)

    def _watch(self, topic: str, model: type[DataModel]) -> None:
        if topic in self._ready:
            return
        self._ready[topic] = asyncio.Event()
        self._unassigned.add(topic)
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consume(), name=f"{self.name}.consumer")

    async def _consume(self) -> None:
        """The process's one consumer, reopened with backoff if it fails."""
        from aiokafka import AIOKafkaConsumer

        delay = _RECONNECT_DELAY
        while True:
            consumer = AIOKafkaConsumer(
                bootstrap_servers=self.bootstrap_servers,
                group_id=None,
                enable_auto_commit=False,
                auto_offset_reset="latest",
            )
            try:
                await consumer.start()
                self._unassigned |= set(self._ready)  # a fresh consumer holds nothing
                while True:
                    if self._unassigned:
                        await self._assign(consumer)
                    batches = await consumer.getmany(timeout_ms=_POLL_MS)
                    for partition, records in batches.items():
                        self._decode(partition.topic, records)
                    delay = _RECONNECT_DELAY
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("%s: consumer failed: %s; reopening in %.0fs", self.name, error, delay)
            finally:
                for event in self._ready.values():
                    event.clear()
                await _stop(consumer)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RECONNECT_DELAY)

    async def _assign(self, consumer: Any) -> None:
        """Add the unassigned topics, each read from its end, keeping the
        position on the topics already held."""
        from aiokafka.structs import TopicPartition

        new = sorted(self._unassigned)
        self._unassigned.clear()
        for topic in new:
            await self._create(topic)
        held = {tp: await consumer.position(tp) for tp in consumer.assignment()}
        fresh = [TopicPartition(topic, 0) for topic in new if TopicPartition(topic, 0) not in held]
        consumer.assign([*held, *fresh])
        for tp, offset in held.items():
            consumer.seek(tp, offset)
        if fresh:
            await consumer.seek_to_end(*fresh)
            for tp in fresh:
                await consumer.position(tp)
        for topic in new:
            self._ready[topic].set()

    def _decode(self, topic: str, records: Sequence[Any]) -> None:
        model = self._models.get(topic)
        if model is None:
            return
        for record in records:
            try:
                message = model.model_validate_json(record.value)
            except Exception as error:
                logger.warning("%s: dropping an undecodable record on %s: %s", self.name, topic, error)
                continue
            if record.timestamp is not None and record.timestamp >= 0:
                stamp_sent_at(message, record.timestamp / 1000.0)  # the producer's CreateTime
            self._deliver(topic, record.key.decode() if record.key else "", message)


async def _stop(consumer: Any) -> None:
    """Stop a consumer, absorbing the cancellation aiokafka may raise on shutdown."""
    try:
        await consumer.stop()
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise
