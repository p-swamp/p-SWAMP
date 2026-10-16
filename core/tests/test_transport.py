"""The in-memory transport, the outbox, and choosing a transport from the environment."""

from __future__ import annotations

import asyncio

import pytest
from support import Measurement, Number, NumberResult, at, measurement, take
from transport_suite import TransportSuite

from pswamp_core.settings import MissingSettingError
from pswamp_core.subscription import Overflow
import pswamp_core.transport as transport_module
from pswamp_core.transport import InMemoryTransport, Outbox, transport_from_env
from pswamp_models.player import PauseCommand


class TestInMemoryTransport(TransportSuite):
    @pytest.fixture
    def transport(self):
        return InMemoryTransport()


async def test_a_full_queue_drops_its_oldest_and_grow_keeps_all():
    broker = InMemoryTransport()
    with broker.subscribe(Measurement, app="a", maxsize=2) as bounded, broker.subscribe(
        Measurement, app="a", overflow=Overflow.GROW
    ) as everything:
        for i in range(5):
            await broker.publish(measurement(i), app="a", key="k")
        assert [m.mRID for _, m in await take(bounded, 2)] == ["m3", "m4"]
        assert bounded.dropped == 3
        assert len(await take(everything, 5)) == 5


async def test_a_closed_subscription_ends_its_iteration():
    broker = InMemoryTransport()
    feed = broker.subscribe(Measurement, app="a")
    feed.close()
    assert [item async for item in feed] == []
    await broker.publish(measurement(1), app="a", key="k")  # nobody listening: fine


async def test_the_outbox_sends_in_order_under_its_key():
    broker = InMemoryTransport()
    outbox = Outbox(broker, app="a", key="k")
    with broker.subscribe(Measurement, app="a", overflow=Overflow.GROW) as feed:
        outbox.start()
        for i in range(3):
            outbox.publish(measurement(i))
        got = await take(feed, 3)
        await outbox.close()
    assert [(key, m.mRID) for key, m in got] == [("k", "m0"), ("k", "m1"), ("k", "m2")]


async def test_the_outbox_takes_a_key_per_message_and_a_new_key_applies_from_then_on():
    broker = InMemoryTransport()
    outbox = Outbox(broker, app="a", key="k#1.0")
    with broker.subscribe(Measurement, app="a", overflow=Overflow.GROW) as feed:
        outbox.publish(measurement(0))
        outbox.publish(measurement(1), key="k#1.0")
        outbox.key = "k#1.1"
        outbox.publish(measurement(2))
        outbox.start()
        got = await take(feed, 3)
        await outbox.close()
    assert [key for key, _ in got] == ["k#1.0", "k#1.0", "k#1.1"]


async def test_a_subscription_to_a_run_hears_every_key_of_that_run_and_no_other():
    broker = InMemoryTransport()
    with broker.subscribe(Measurement, app="a", key="42", overflow=Overflow.GROW) as feed:
        for key in ("42", "42#7.0", "42#8.3", "420", "4", "42x#1.0"):
            await broker.publish(measurement(1), app="a", key=key)
        got = [feed.get_nowait() for _ in range(3)]
        assert feed.get_nowait() is None
    assert [key for key, _ in got] == ["42", "42#7.0", "42#8.3"]


async def test_a_full_outbox_drops_old_data_but_never_a_command():
    broker = InMemoryTransport()
    outbox = Outbox(broker, app="a", key="k", maxsize=2)
    with broker.subscribe(Measurement, PauseCommand, app="a", overflow=Overflow.GROW) as feed:
        outbox.publish(PauseCommand())
        for i in range(4):
            outbox.publish(measurement(i))  # not started: everything waits
        outbox.start()
        got = await take(feed, 3)
        await outbox.close()
    assert isinstance(got[0][1], PauseCommand)
    assert [m.mRID for _, m in got[1:]] == ["m2", "m3"]
    assert outbox.dropped == 2


async def test_a_full_outbox_never_drops_an_answer_to_a_command():
    def result(value: float, request_id: str | None = None) -> NumberResult:
        return NumberResult(timestamp=at(0), app={"name": "n", "uuid": "u"}, result=Number(value=value), request_id=request_id)

    broker = InMemoryTransport()
    outbox = Outbox(broker, app="a", key="k", maxsize=2)
    with broker.subscribe(NumberResult, app="a", overflow=Overflow.GROW) as feed:
        outbox.publish(result(0, request_id="asked"))
        for i in range(1, 5):
            outbox.publish(result(i))  # not started: everything waits
        outbox.start()
        got = await take(feed, 3)
        await outbox.close()
    assert [(r.result.value, r.request_id) for _, r in got] == [(0, "asked"), (3, None), (4, None)]


async def test_closing_the_outbox_flushes_it():
    broker = InMemoryTransport()
    outbox = Outbox(broker, app="a", key="k")
    with broker.subscribe(Measurement, app="a") as feed:
        outbox.publish(measurement(1))
        await outbox.close()
        await asyncio.sleep(0)
        assert feed.get_nowait()[1].mRID == "m1"


class Refusing(InMemoryTransport):
    """Refuses its first ``refusals`` publishes, or every one."""

    def __init__(self, refusals: int | None = None) -> None:
        super().__init__()
        self.refusals = refusals
        self.attempts = 0

    async def publish(self, message, *, app, key):
        self.attempts += 1
        if self.refusals is None or self.attempts <= self.refusals:
            raise ConnectionError("broker down")
        await super().publish(message, app=app, key=key)


async def eventually(condition, timeout: float = 2.0) -> None:
    async def poll():
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


async def test_the_outbox_publishes_a_command_again_until_the_transport_takes_it(monkeypatch):
    monkeypatch.setattr(transport_module, "_RETRY_S", 0.01)
    broker, undelivered = Refusing(refusals=2), []
    outbox = Outbox(broker, app="a", key="k", on_undelivered=lambda message, error: undelivered.append(message))
    with broker.subscribe(PauseCommand, app="a") as feed:
        outbox.start()
        outbox.publish(PauseCommand())
        await take(feed, 1)
        await outbox.close()
    assert (broker.attempts, outbox.published, outbox.failed, undelivered) == (3, 1, 2, [])


async def test_the_outbox_gives_up_on_a_command_at_its_deadline_and_says_so(monkeypatch):
    monkeypatch.setattr(transport_module, "_RETRY_S", 0.01)
    undelivered = []
    outbox = Outbox(Refusing(), app="a", key="k", deadline=0.1, on_undelivered=lambda *given: undelivered.append(given))
    outbox.start()
    outbox.publish(measurement(1))  # data: tried once, then dropped, as before
    command = PauseCommand()
    outbox.publish(command)
    await eventually(lambda: undelivered)
    ((message, error),) = undelivered
    assert message is command and isinstance(error, ConnectionError)
    assert (outbox.published, outbox.undelivered) == (0, 1) and outbox.failed > 2  # tried again meanwhile
    await outbox.close()


async def test_a_command_still_queued_at_its_deadline_is_given_up_unsent():
    broker, undelivered = InMemoryTransport(), []
    outbox = Outbox(broker, app="a", key="k", deadline=0.05, on_undelivered=lambda *given: undelivered.append(given))
    command = PauseCommand()
    outbox.publish(command)  # not started: it waits, past its deadline
    await asyncio.sleep(0.1)
    outbox.start()
    await eventually(lambda: undelivered)
    assert undelivered == [(command, None)] and outbox.published == 0
    await outbox.close()


def test_the_transport_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("T", raising=False)
    assert isinstance(transport_from_env("T"), InMemoryTransport)
    monkeypatch.setenv("T", "mem:pswamp_core.transport:InMemoryTransport")
    transport = transport_from_env("T")
    assert isinstance(transport, InMemoryTransport) and transport.name == "mem"
    for bad in ("not-a-spec", "x:pswamp_models.pmu:PmuFrame", "x:no.such.module:X"):
        monkeypatch.setenv("T", bad)
        with pytest.raises(MissingSettingError):
            transport_from_env("T")
