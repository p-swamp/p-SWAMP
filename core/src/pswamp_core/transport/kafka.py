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
- **Reconnecting.** A consumer that fails (the broker went away) is reopened
  with backoff. It resumes each control topic (commands, errors,
  ``PipelineClosed``) where it was, so what was published meanwhile still
  arrives; a receiver refuses a command that arrives too late
  (``CommandInbox``). A data topic starts again at its end. A control topic
  whose offsets no longer fit (the broker lost it and made it again) is read
  from its start.
- **Order.** Kafka keeps order within a topic only, and each class has its
  own topic. Each fetch is delivered each topic in its own order, the topics
  interleaved by when each record was sent (its CreateTime; within one ms, a
  command's issue time). So commands of different classes apply as sent,
  also when a reconnect fetches everything sent meanwhile at once.
- **A broker that lost its topics** (a new broker with no volume) is noticed
  both ways. A publish that fails makes its topic again on the next try. The
  consumer checks every ``_TOPIC_CHECK_S`` that the topics it holds still
  exist, and reopens if not; assigning, it asks the broker which exist rather
  than trusting what this process made, and makes the others again.
- **Backpressure.** ``publish`` waits for the broker's acknowledgement, so a
  slow broker backs up into the caller's ``Outbox``, which drops old data.

Needs the ``kafka`` extra. aiokafka is imported where it is used, so naming
this class costs nothing without it.
"""

from __future__ import annotations

import asyncio
import heapq
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pswamp_models.common import Command, stamp_sent_at

from ..log import get_logger
from ..settings import EnvSetting
from . import _CONTROL, Transport

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

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
#: How often the consumer checks that the topics it holds still exist.
_TOPIC_CHECK_S = 2.0


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
        #: Per control topic, the next offset to read: where a reopened
        #: consumer resumes.
        self._resume_at: dict[str, int] = {}
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
        try:
            await self._producer.send_and_wait(topic, value=message.model_dump_json().encode(), key=key.encode())
        except Exception:
            self._created.discard(topic)  # it may be gone: make it again on the next try
            raise

    async def _create(self, topic: str) -> None:
        """Create ``topic`` if the broker lacks it. A refusal is logged and left
        to the produce or consume that follows."""
        if topic in self._created:
            return
        from aiokafka.admin import NewTopic
        from aiokafka.errors import TopicAlreadyExistsError

        admin = await self._admin_client()
        new = NewTopic(topic, num_partitions=1, replication_factor=self.replication_factor, topic_configs=LIVE_TOPIC_CONFIGS)
        try:
            response = await admin.create_topics([new])
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

    async def _admin_client(self) -> Any:
        """The admin client, started on first use. It is kept only once started:
        aiokafka's client answers nothing until its start has succeeded, so one
        kept after a failed start made every later ``_create`` wait for ever."""
        async with self._open_lock:
            if self._admin is None:
                from aiokafka.admin import AIOKafkaAdminClient

                admin = AIOKafkaAdminClient(bootstrap_servers=self.bootstrap_servers, request_timeout_ms=10_000)
                await admin.start()
                self._admin = admin
            return self._admin

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
                request_timeout_ms=10_000,  # a request that cannot succeed fails in 10 s, not 40
            )
            try:
                await consumer.start()
                self._unassigned |= set(self._ready)  # a fresh consumer holds nothing
                checked = time.monotonic()
                while True:
                    if self._unassigned:
                        await self._assign(consumer)
                    self._decode(await consumer.getmany(timeout_ms=_POLL_MS))
                    delay = _RECONNECT_DELAY
                    if time.monotonic() - checked >= _TOPIC_CHECK_S:
                        checked = time.monotonic()
                        await self._check_topics(consumer)
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
        present = await consumer.topics()  # fresh metadata: a new broker has none of them
        for topic in new:
            if topic not in present:
                self._created.discard(topic)
            await self._create(topic)
        held = {tp: await consumer.position(tp) for tp in consumer.assignment()}
        fresh = [TopicPartition(topic, 0) for topic in new if TopicPartition(topic, 0) not in held]
        consumer.assign([*held, *fresh])
        for tp, offset in held.items():
            consumer.seek(tp, offset)
        resumed = {tp: self._resume_at[tp.topic] for tp in fresh if tp.topic in self._resume_at}
        if resumed:
            starts = await consumer.beginning_offsets(list(resumed))
            ends = await consumer.end_offsets(list(resumed))
            for tp, offset in resumed.items():
                consumer.seek(tp, offset if starts[tp] <= offset <= ends[tp] else starts[tp])
        at_end = [tp for tp in fresh if tp not in resumed]
        if at_end:
            await consumer.seek_to_end(*at_end)
            for tp in at_end:
                position = await consumer.position(tp)
                if self._is_control(tp.topic):
                    self._resume_at[tp.topic] = position
        for topic in new:
            self._ready[topic].set()

    async def _check_topics(self, consumer: Any) -> None:
        """Raise when a topic the consumer holds is gone from the broker, so
        that it is reopened and, re-assigning, makes the topic again. A
        consumer of a lost topic only logs; it never raises on its own."""
        held = {tp.topic for tp in consumer.assignment()}
        if not held:
            return
        missing = held - await consumer.topics()  # fresh metadata from the broker
        if missing:
            self._created.difference_update(missing)
            names = ", ".join(sorted(missing)[:3]) + (", ..." if len(missing) > 3 else "")
            raise LookupError(f"the broker lost {len(missing)} of the topics read here ({names}); making them again")

    def _is_control(self, topic: str) -> bool:
        model = self._models.get(topic)
        return model is not None and issubclass(model, _CONTROL)

    def _decode(self, batches: dict[Any, Sequence[Any]]) -> None:
        """Deliver one fetch: each topic in its own order, the topics
        interleaved by when each record was sent. Kafka keeps order within a
        topic only, and each class has its own, so a pause then a play would
        otherwise arrive in whatever order the fetch lists their topics; after
        a reconnect, everything sent meanwhile is one fetch."""
        topics = []
        for partition, records in batches.items():
            topic = partition.topic
            model = self._models.get(topic)
            if model is None:
                continue
            received = []
            for record in records:
                try:
                    message = model.model_validate_json(record.value)
                except Exception as error:
                    logger.warning("%s: dropping an undecodable record on %s: %s", self.name, topic, error)
                    continue
                if record.timestamp is not None and record.timestamp >= 0:
                    stamp_sent_at(message, record.timestamp / 1000.0)  # the producer's CreateTime
                received.append((topic, record, message))
            topics.append(received)
            if records and topic in self._resume_at:
                self._resume_at[topic] = records[-1].offset + 1
        # merge, not sort: a topic's own order stands even if producers' clocks differ
        for topic, record, message in heapq.merge(*topics, key=_sent_order):
            self._deliver(topic, record.key.decode() if record.key else "", message)


def _sent_order(item: tuple[str, Any, DataModel]) -> tuple[int, float]:
    """When a record was sent, in ms; within one ms, a command's issue time."""
    _, record, message = item
    sent = record.timestamp if record.timestamp is not None and record.timestamp >= 0 else 0
    return sent, message.timestamp.timestamp() if isinstance(message, Command) else 0.0


async def _stop(consumer: Any) -> None:
    """Stop a consumer, absorbing the cancellation aiokafka may raise on shutdown."""
    try:
        await consumer.stop()
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise
