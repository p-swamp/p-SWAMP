"""Falling behind is reported: by a module over its input, and by the outbox."""

from __future__ import annotations

import asyncio
import time
from typing import ClassVar

from support import Measurement, Number, NumberResult, Recorder, measurement, queue

from pswamp_core.keep_up import KeepUp, KeepUpMonitor
from pswamp_core.modules import Module
from pswamp_core.subscription import Overflow
from pswamp_core.transport import InMemoryTransport, Outbox
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.common import ErrorEvent, sent_at, stamp_sent_at


class Slow(Module):
    name = "slow"
    input_model = Measurement
    output_model = NumberResult
    keep_up: ClassVar[KeepUp | None] = KeepUp(max_input_age_s=1.0, report_every_s=0.05)

    async def process(self, message: Measurement) -> Number:
        await asyncio.sleep(0.01)
        return Number(value=message.value)


class Quiet(Slow):
    keep_up = None


async def test_the_transport_stamps_when_a_message_was_sent():
    broker = InMemoryTransport()
    with broker.subscribe(Measurement, app="a") as feed:
        sent = measurement(1)
        await broker.publish(sent, app="a", key="k")
        _, got = feed.get_nowait()
    assert sent_at(sent) is None and abs(time.time() - sent_at(got)) < 1


async def test_a_module_reports_dropped_input_then_catching_up():
    inputs, out = queue(Measurement, overflow=Overflow.DROP_OLDEST, maxsize=2), Recorder()
    task = asyncio.create_task(Slow().run(inputs, out))
    for i in range(10):  # a burst into a queue of two: most are dropped
        inputs.offer(measurement(i))
    (behind,) = await out.wait_for(ErrorEvent)
    assert behind.message == "slow is not keeping up with measurement" and "dropped" in behind.detail
    await asyncio.sleep(0.1)
    for i in range(3):  # now at a pace it keeps up with
        inputs.offer(measurement(i))
        await asyncio.sleep(0.03)
    caught_up = (await out.wait_for(ErrorEvent, 2))[1]
    assert caught_up.message.startswith("slow caught up")
    await cancel_and_wait(task)


async def test_old_input_counts_as_behind_and_no_policy_reports_nothing():
    monitor, out = KeepUpMonitor("m", "is behind", KeepUp(max_input_age_s=1.0)), Recorder()
    old = measurement(1)
    stamp_sent_at(old, time.time() - 5)
    monitor.observe(queue(Measurement), old, out)
    assert monitor.behind and "5.0 s after it was sent" in out.of(ErrorEvent)[0].detail
    silent, out = Quiet(), Recorder()
    inputs = queue(Measurement, overflow=Overflow.DROP_OLDEST, maxsize=1)
    for i in range(5):
        inputs.offer(measurement(i))
    task = asyncio.create_task(silent.run(inputs, out))
    await asyncio.sleep(0.05)
    await cancel_and_wait(task)
    assert out.of(ErrorEvent) == []


async def test_a_full_outbox_reports_what_it_drops():
    broker = InMemoryTransport()
    outbox = Outbox(broker, app="a", key="k", maxsize=1, keep_up=KeepUp(), label="the publisher")
    with broker.subscribe(ErrorEvent, app="a") as errors:
        for i in range(3):
            outbox.publish(measurement(i))  # not started: the queue overflows
        outbox.start()
        _, report = await asyncio.wait_for(errors.get(), 5)
        await outbox.close()
    assert report.message == "the publisher cannot publish as fast as it produces" and outbox.dropped == 2
