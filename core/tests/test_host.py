"""A host runs one module instance per key, off the transport."""

from __future__ import annotations

import asyncio

from support import Measurement, Number, NumberResult, measurement, take
from test_modules import Doubler, HalveCommand, Halver

from pswamp_core.host import ModuleHost
from pswamp_core.subscription import Overflow
from pswamp_core.transport import InMemoryTransport
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


async def test_an_instance_that_fails_is_reported_and_dropped_and_built_again_later():
    class Flaky(Doubler):
        setups = 0

        async def setup(self, out) -> None:
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
        async def handle(self, command: HalveCommand):
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


async def test_a_module_that_reads_the_gateway_gets_its_own():
    from support import ListClient

    from pswamp_core.datagateway import DataGateway

    class Reader(Doubler):
        reads_gateway = True
        gateways: list = []

        async def setup(self, out) -> None:
            Reader.gateways.append(self.gateway)

    broker = InMemoryTransport()
    host = ModuleHost(Reader, broker, app="a", gateway=lambda: DataGateway([ListClient()]))
    task = asyncio.create_task(host.serve())
    await settle()
    for key in ("k1", "k2"):
        await broker.publish(measurement(1), app="a", key=key)
    await settle()
    assert len(Reader.gateways) == 2 and Reader.gateways[0] is not Reader.gateways[1]
    await cancel_and_wait(task)
