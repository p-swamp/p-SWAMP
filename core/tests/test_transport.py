"""The in-memory transport, the outbox, and choosing a transport from the environment."""

from __future__ import annotations

import asyncio

import pytest
from support import Measurement, Number, NumberResult, at, measurement, take
from transport_suite import TransportSuite

from pswamp_core.settings import MissingSettingError
from pswamp_core.subscription import Overflow
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
