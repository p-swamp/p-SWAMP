"""A host runs one module instance per key, off the transport."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from support import Measurement, Number, NumberResult, at, measurement, take
from test_modules import (
    Alarm,
    Assessment,
    Doubler,
    Estimate,
    HalveCommand,
    Halver,
    Monitor,
    Overlapping,
    Snapshot,
    TextResult,
)

from pswamp_core.host import ModuleHost
from pswamp_core.modules import Module
from pswamp_core.subscription import Overflow
from pswamp_core.transport import CONTROL_DEADLINE_S, InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_core.util.time import utcnow
from pswamp_models.common import ErrorEvent, PipelineClosed


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_one_instance_per_key_and_results_under_that_key():
    broker = InMemoryTransport()
    host = ModuleHost(Doubler, broker, app="a")
    task = asyncio.create_task(host.serve())
    await settle()
    with broker.subscribe(NumberResult, app="a", overflow=Overflow.GROW) as results:
        await broker.publish(measurement(1), app="a", key="k1")
        await broker.publish(measurement(2), app="a", key="k2")
        await broker.publish(measurement(3), app="a", key="k1")
        got = await take(results, 3)
    assert sorted(host.keys()) == ["k1", "k2"]
    assert sorted((key, r.result.value) for key, r in got) == [("k1", 2.0), ("k1", 6.0), ("k2", 4.0)]
    uuids = {key: r.app.uuid for key, r in got}
    assert uuids["k1"] != uuids["k2"]
    await cancel_and_wait(task)


async def test_pipeline_closed_drops_the_instance():
    broker = InMemoryTransport()
    host = ModuleHost(Doubler, broker, app="a")
    task = asyncio.create_task(host.serve())
    await settle()
    await broker.publish(measurement(1), app="a", key="k")
    await settle()
    assert host.keys() == ["k"]
    await broker.publish(PipelineClosed(timestamp=utcnow(), reason="idle"), app="a", key="k")
    await settle()
    assert host.keys() == []
    await cancel_and_wait(task)


async def test_an_idle_instance_is_dropped():
    broker = InMemoryTransport()
    host = ModuleHost(Doubler, broker, app="a", idle_seconds=0.1)
    task = asyncio.create_task(host.serve())
    await settle()
    await broker.publish(measurement(1), app="a", key="k")
    await settle()
    assert host.keys() == ["k"]
    await asyncio.sleep(0.3)
    assert host.keys() == []
    await cancel_and_wait(task)


class TornDown(Doubler):
    """Doubler that records its teardown."""

    def __init__(self, fail: bool = False) -> None:
        super().__init__()
        self.fail = fail
        self.torn_down = 0

    async def teardown(self) -> None:
        self.torn_down += 1
        if self.fail:
            raise RuntimeError("teardown failed")


def recording(fail: bool = False):
    """A factory of ``TornDown`` instances, and the list it builds into
    (the first is the host's template)."""
    instances: list[TornDown] = []

    def build() -> TornDown:
        instances.append(TornDown(fail))
        return instances[-1]

    return build, instances


async def test_a_newer_run_of_a_key_gets_a_fresh_instance_and_an_older_one_is_ignored():
    build, instances = recording()
    broker = InMemoryTransport()
    host = ModuleHost(build, broker, app="a")
    task = asyncio.create_task(host.serve())
    await settle()
    with broker.subscribe(NumberResult, app="a", overflow=Overflow.GROW) as results:
        await broker.publish(measurement(1), app="a", key="k#100.0")
        await broker.publish(measurement(2), app="a", key="k#200.0")
        (_, first), (_, second) = await take(results, 2)
        await broker.publish(measurement(3), app="a", key="k#100.0")  # late, from the old run
        await asyncio.sleep(0.05)  # and the old instance's drop runs to its teardown
        assert results.get_nowait() is None
    assert first.app.uuid != second.app.uuid and host.keys() == ["k"]
    old, new = instances[1:]
    assert old.torn_down == 1 and new.torn_down == 0
    await cancel_and_wait(task)
    assert new.torn_down == 1  # at shutdown


async def test_a_late_pipeline_closed_of_an_older_run_leaves_the_newer_instance():
    build, instances = recording()
    broker = InMemoryTransport()
    host = ModuleHost(build, broker, app="a")
    task = asyncio.create_task(host.serve())
    await settle()
    await broker.publish(measurement(1), app="a", key="k#200.0")
    await settle()
    await broker.publish(PipelineClosed(timestamp=utcnow(), reason="idle"), app="a", key="k#100.0")
    await settle()
    assert host.keys() == ["k"]
    await broker.publish(PipelineClosed(timestamp=utcnow(), reason="idle"), app="a", key="k#200.3")
    await asyncio.sleep(0.05)  # the drop runs to its teardown
    assert host.keys() == [] and instances[1].torn_down == 1
    await cancel_and_wait(task)


async def test_an_idle_instance_is_torn_down_and_a_failing_teardown_is_only_logged():
    build, instances = recording(fail=True)
    broker = InMemoryTransport()
    host = ModuleHost(build, broker, app="a", idle_seconds=0.1)
    task = asyncio.create_task(host.serve())
    await settle()
    await broker.publish(measurement(1), app="a", key="k1")
    await asyncio.sleep(0.3)
    assert host.keys() == [] and instances[1].torn_down == 1
    with broker.subscribe(NumberResult, app="a", key="k2") as results:
        await broker.publish(measurement(2), app="a", key="k2")
        (_, result), = await take(results, 1)
    assert result.result.value == 4  # the host still serves
    await cancel_and_wait(task)


class Streamed(Module):
    """Records its calls; slow on a value of 1, to have a call in flight."""

    name = "streamed"
    inputs = (Measurement,)
    outputs = (NumberResult,)
    blocking = True

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def process(self, message: Measurement) -> Number:
        if message.value == 1:
            time.sleep(0.1)
        self.calls.append(f"process {message.value:g}")
        return Number(value=message.value)

    def reset(self) -> None:
        self.calls.append("reset")


async def test_a_new_stream_voids_the_queue_and_resets_after_the_call_in_flight():
    instances: list[Streamed] = []

    def build() -> Streamed:
        instances.append(Streamed())
        return instances[-1]

    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(build, broker, app="a").serve())
    await settle()
    with broker.subscribe(NumberResult, app="a", key="k", overflow=Overflow.GROW) as results:
        await broker.publish(measurement(1), app="a", key="k#1.1")
        await asyncio.sleep(0.03)  # 1 is being processed
        await broker.publish(measurement(2), app="a", key="k#1.1")  # queued, then void
        await broker.publish(measurement(3), app="a", key="k#1.2")  # a seek
        await broker.publish(measurement(4), app="a", key="k#1.1")  # late, from before it
        got = await take(results, 2)
        await asyncio.sleep(0.05)
        assert results.get_nowait() is None
    assert [(key, r.result.value) for key, r in got] == [("k#1.1", 1), ("k#1.2", 3)]
    assert instances[1].calls == ["process 1", "reset", "process 3"]
    await cancel_and_wait(task)


async def test_a_join_forgets_its_inputs_when_the_stream_starts_over():
    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(Assessment, broker, app="a").serve())
    await settle()
    with broker.subscribe(NumberResult, app="a", key="k", overflow=Overflow.GROW) as outputs:
        for message in (Snapshot(load_mw=100, timestamp=at(58)), Measurement(value=1, timestamp=at(58))):
            await broker.publish(message, app="a", key="k#1.1")
        await broker.publish(Estimate(n=1, timestamp=at(58.5)), app="a", key="k#1.1")
        ((_, before),) = await take(outputs, 1)
        # Seek back to 10 s: the inputs from 58 s are not "fresh" for a trigger at 10 s.
        await broker.publish(Estimate(n=2, timestamp=at(10)), app="a", key="k#1.2")
        await settle()
        assert outputs.get_nowait() is None
        # A new stream's other inputs, arriving before its first trigger, are kept.
        for message in (Snapshot(load_mw=200, timestamp=at(20)), Measurement(value=2, timestamp=at(20))):
            await broker.publish(message, app="a", key="k#1.3")
        await broker.publish(Estimate(n=3, timestamp=at(20)), app="a", key="k#1.3")
        ((key, after),) = await take(outputs, 1)
    assert before.result.value == 1 + 100 + 1 and (key, after.result.value) == ("k#1.3", 2 + 200 + 3)
    await cancel_and_wait(task)


async def test_commands_reach_the_instance_for_their_key_and_refusals_come_back():
    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(Halver, broker, app="a").serve())
    await settle()
    with broker.subscribe(NumberResult, ErrorEvent, app="a", key="k", overflow=Overflow.GROW) as answers:
        ok, refused = HalveCommand(value=10), HalveCommand(value=-1)
        await broker.publish(ok, app="a", key="k")
        await broker.publish(refused, app="a", key="k")
        (_, result), (_, error) = await take(answers, 2)
    assert result.result.value == 5 and result.request_id == ok.request_id
    assert error.request_id == refused.request_id
    await cancel_and_wait(task)


async def test_an_input_and_a_command_never_run_in_an_instance_at_once():
    instances: list[Overlapping] = []

    def build() -> Overlapping:
        instances.append(Overlapping())
        return instances[-1]

    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(build, broker, app="a").serve())
    await settle()
    with broker.subscribe(NumberResult, app="a", key="k", overflow=Overflow.GROW) as results:
        await broker.publish(measurement(1), app="a", key="k")
        await broker.publish(HalveCommand(value=4), app="a", key="k")
        await broker.publish(measurement(2), app="a", key="k")
        await take(results, 3)
    (module,) = instances[1:]  # the first is the host's template
    assert len(module.calls) == 3 and not module.overlapped()
    await cancel_and_wait(task)


async def test_a_command_issued_too_long_ago_is_reported_not_applied():
    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(Halver, broker, app="a").serve())
    await settle()
    with broker.subscribe(NumberResult, ErrorEvent, app="a", key="k", overflow=Overflow.GROW) as answers:
        late = HalveCommand(value=10, timestamp=utcnow() - timedelta(seconds=CONTROL_DEADLINE_S + 5))
        fresh = HalveCommand(value=8)
        await broker.publish(late, app="a", key="k")
        await broker.publish(fresh, app="a", key="k")
        (_, error), (_, result) = await take(answers, 2)
    assert error.request_id == late.request_id and "did not apply halve" in error.message
    assert (result.result.value, result.request_id) == (4, fresh.request_id)
    await cancel_and_wait(task)


async def test_an_instance_that_fails_is_reported_and_dropped_and_built_again_later():
    class Flaky(Doubler):
        setups = 0

        async def setup(self) -> None:
            Flaky.setups += 1
            if Flaky.setups == 1:
                raise RuntimeError("no source")

    broker = InMemoryTransport()
    host = ModuleHost(Flaky, broker, app="a", retry_seconds=0.1)
    task = asyncio.create_task(host.serve())
    await settle()
    with broker.subscribe(NumberResult, ErrorEvent, app="a", key="k", overflow=Overflow.GROW) as answers:
        await broker.publish(measurement(1), app="a", key="k")
        ((_, error),) = await take(answers, 1)
        await settle()
        assert error.source == "doubler" and error.detail == "RuntimeError: no source"
        assert host.keys() == []
        await broker.publish(measurement(2), app="a", key="k")  # too soon: the key is left alone
        await settle()
        assert host.keys() == [] and Flaky.setups == 1
        await asyncio.sleep(0.15)
        await broker.publish(measurement(3), app="a", key="k")
        ((_, result),) = await take(answers, 1)
    assert result.result.value == 6.0 and host.keys() == ["k"]
    await cancel_and_wait(task)


async def test_a_bad_answer_for_one_key_does_not_end_the_host():
    class Misanswering(Halver):
        def handle(self, command: HalveCommand):
            return Measurement() if command.value == 1 else Number(value=command.value / 2)

    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(Misanswering, broker, app="a").serve())
    await settle()
    with broker.subscribe(NumberResult, ErrorEvent, app="a", overflow=Overflow.GROW) as answers:
        await broker.publish(HalveCommand(value=1), app="a", key="k1")
        ((key, error),) = await take(answers, 1)
        assert key == "k1" and isinstance(error, ErrorEvent)
        await broker.publish(PipelineClosed(timestamp=utcnow(), reason="idle"), app="a", key="k1")
        await broker.publish(HalveCommand(value=8), app="a", key="k2")
        ((key, result),) = await take(answers, 1)
    assert key == "k2" and result.result.value == 4
    assert not task.done()
    await cancel_and_wait(task)


async def test_a_host_ignores_what_its_module_does_not_read():
    broker = InMemoryTransport()
    host = ModuleHost(Halver, broker, app="a")
    task = asyncio.create_task(host.serve())
    await settle()
    await broker.publish(Measurement(value=1), app="a", key="k")
    await settle()
    assert host.keys() == []
    await cancel_and_wait(task)


async def test_a_module_that_reads_the_sources_gets_its_own():
    from support import ListSource

    from pswamp_core.sources import SourceSet

    class Reader(Doubler):
        reads_sources = True
        source_sets: list = []

        async def setup(self) -> None:
            Reader.source_sets.append(self.sources)

    broker = InMemoryTransport()
    host = ModuleHost(Reader, broker, app="a", sources=lambda: SourceSet([ListSource()]))
    task = asyncio.create_task(host.serve())
    await settle()
    for key in ("k1", "k2"):
        await broker.publish(measurement(1), app="a", key=key)
    await settle()
    assert len(Reader.source_sets) == 2 and Reader.source_sets[0] is not Reader.source_sets[1]
    await cancel_and_wait(task)


async def test_a_host_reads_every_input_of_a_module():
    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(Monitor, broker, app="a").serve())
    await settle()
    with broker.subscribe(NumberResult, TextResult, app="a", key="k", overflow=Overflow.GROW) as outputs:
        await broker.publish(Alarm(level=5, timestamp=at(0)), app="a", key="k")
        ((_, text),) = await take(outputs, 1)
        await broker.publish(measurement(1), app="a", key="k")
        ((_, number),) = await take(outputs, 1)
    assert text.result.text == "level 5" and number.result.value == 6.0
    await cancel_and_wait(task)


async def test_joined_inputs_only_the_trigger_queues():
    broker = InMemoryTransport()
    host = ModuleHost(Assessment, broker, app="a")  # maxsize 2
    task = asyncio.create_task(host.serve())
    await settle()
    assert host.inputs == (Estimate,) and set(host.observed) == {Measurement, Snapshot}
    with broker.subscribe(NumberResult, ErrorEvent, app="a", key="k", overflow=Overflow.GROW) as outputs:
        await broker.publish(Snapshot(load_mw=100, timestamp=at(0)), app="a", key="k")
        for i in range(200):  # a fast stream: it only replaces the newest, never queues
            await broker.publish(Measurement(value=i, timestamp=at(i / 100)), app="a", key="k")
        await settle()
        await broker.publish(Estimate(n=1, timestamp=at(2)), app="a", key="k")
        ((_, result),) = await take(outputs, 1)
        assert result.result.value == 199 + 100 + 1 and result.timestamp == at(2)
        await broker.publish(Estimate(n=1, timestamp=at(5)), app="a", key="k")  # the measurement is stale now
        await settle()
        assert outputs.get_nowait() is None
    assert host._slots["k"].inputs.dropped == 0
    await cancel_and_wait(task)


async def test_an_undeclared_output_from_a_hosted_module_is_an_error_event():
    class Sloppy(Doubler):
        def process(self, message):
            return Snapshot()

    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(Sloppy, broker, app="a").serve())
    await settle()
    with broker.subscribe(ErrorEvent, app="a", key="k") as errors:
        await broker.publish(measurement(1), app="a", key="k")
        ((_, error),) = await take(errors, 1)
    assert error.source == "doubler" and "Snapshot, which is not in its outputs" in error.detail
    await cancel_and_wait(task)
