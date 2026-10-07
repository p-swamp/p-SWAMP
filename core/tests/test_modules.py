"""A module: declared inputs in, declared outputs out, synchronous code between.
Called directly (``run``), fed from a queue (``serve_module``), and answering
commands through its inbox."""

from __future__ import annotations

import asyncio
import threading
from typing import Literal

import pytest
from pydantic import BaseModel
from support import Measurement, Number, NumberResult, Recorder, at, measurement, queue

from pswamp_core.command_routing import CommandRefused, concrete_commands
from pswamp_core.host import command_inbox, serve_module
from pswamp_core.modules import Latest, Module, UndeclaredOutput, on
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.common import Command, DataModel, ErrorEvent, ResultEnvelope
from pswamp_models.player import PauseCommand, PlayerCommand


class Doubler(Module):
    name = "doubler"
    inputs = (Measurement,)
    outputs = (NumberResult,)

    def process(self, message: Measurement) -> Number | None:
        if message.value < 0:
            return None
        if message.value > 100:
            raise ValueError("too big")
        return Number(value=message.value * 2)


class HalveCommand(Command):
    version: Literal["v1"] = "v1"
    value: float


class Halver(Module):
    name = "halver"
    outputs = (NumberResult,)
    commands = (HalveCommand,)

    def validate(self, command: HalveCommand) -> None:
        if command.value < 0:
            raise CommandRefused("no negatives")

    def handle(self, command: HalveCommand) -> Number:
        if command.value == 0:
            raise RuntimeError("cannot halve zero")
        return Number(value=command.value / 2)


# -- stand-in messages for several inputs and outputs -------------------------------


class Alarm(DataModel):
    version: Literal["v1"] = "v1"
    level: int = 0


class Snapshot(DataModel):
    """A stand-in for a slow SCADA snapshot."""

    version: Literal["v1"] = "v1"
    load_mw: float = 0.0


class Estimate(DataModel):
    """A stand-in for a state estimate: the trigger of a join."""

    version: Literal["v1"] = "v1"
    n: int = 0


class Text(BaseModel):
    text: str


class TextResult(ResultEnvelope[Text]):
    version: Literal["v1"] = "v1"


class Monitor(Module):
    """Two independent inputs, one handler each, state kept by the module."""

    name = "monitor"
    inputs = (Measurement, Alarm)
    outputs = (NumberResult, TextResult)

    def __init__(self) -> None:
        super().__init__()
        self.level = 0

    @on(Measurement)
    def on_measurement(self, message: Measurement) -> Number:
        return Number(value=message.value + self.level)

    @on(Alarm)
    def on_alarm(self, alarm: Alarm) -> Text:
        self.level = alarm.level
        return Text(text=f"level {alarm.level}")


class Assessment(Module):
    """Three named inputs, joined: one call per estimate."""

    name = "assessment"
    inputs = {"pmu": Measurement, "scada": Snapshot, "se": Estimate}
    join = Latest(trigger="se", max_age={"pmu": 1.0, "scada": 10.0}, missing="skip")
    outputs = (NumberResult,)
    maxsize = 2

    def process(self, *, pmu: Measurement, scada: Snapshot, se: Estimate) -> Number:
        return Number(value=pmu.value + scada.load_mw + se.n)


class TwoOutputs(Module):
    """One input, a result and a command for the player."""

    name = "two"
    inputs = (Measurement,)
    outputs = (NumberResult, PauseCommand)

    def process(self, message: Measurement) -> list:
        return [Number(value=message.value), PauseCommand()]


# -- calling a module from plain code ------------------------------------------------


def test_run_wraps_the_body_in_the_declared_envelope():
    (result,) = Doubler().run(measurement(3))
    assert isinstance(result, NumberResult)
    assert (result.result.value, result.timestamp, result.app.name) == (6.0, at(3), "doubler")
    assert Doubler().run(Measurement(value=-1, timestamp=at(1))) == []
    assert Doubler().run_one(measurement(4)).result.value == 8.0


def test_run_one_wants_exactly_one_output():
    with pytest.raises(ValueError, match="published 0 messages"):
        Doubler().run_one(Measurement(value=-1, timestamp=at(1)))
    with pytest.raises(ValueError, match="published 2 messages"):
        TwoOutputs().run_one(measurement(1))


def test_a_module_returns_several_declared_outputs():
    result, pause = TwoOutputs().run(measurement(5))
    assert isinstance(result, NumberResult) and result.result.value == 5.0
    assert isinstance(pause, PauseCommand)


def test_an_undeclared_input_or_output_is_an_error():
    with pytest.raises(TypeError, match="does not read Alarm"):
        Doubler().run(Alarm())

    class Sloppy(Doubler):
        def process(self, message):
            return Text(text="not declared")

    with pytest.raises(UndeclaredOutput, match="Text, which is not in its outputs"):
        Sloppy().run(measurement(1))


def test_independent_inputs_reach_their_own_handler():
    monitor = Monitor()
    assert monitor.run_one(measurement(1)).result.value == 1.0
    assert monitor.run_one(Alarm(level=10, timestamp=at(2))).result.text == "level 10"
    assert monitor.run_one(measurement(1)).result.value == 11.0


def test_named_inputs_are_joined_or_passed_by_name():
    module = Assessment()
    assert module.run(Estimate(n=1, timestamp=at(0))) == []  # nothing else yet: skipped
    module.run(Measurement(value=10, timestamp=at(0)))
    module.run(Snapshot(load_mw=100, timestamp=at(0)))
    assert module.run_one(Estimate(n=1, timestamp=at(0.5))).result.value == 111
    assert module.run(Estimate(n=1, timestamp=at(2))) == []  # the measurement is now 2 s old
    direct = Assessment().run_one(
        pmu=Measurement(value=1, timestamp=at(0)), scada=Snapshot(load_mw=2), se=Estimate(n=3, timestamp=at(99))
    )
    assert (direct.result.value, direct.timestamp) == (6, at(99))  # no join: no staleness either


def test_run_command_answers_from_plain_code():
    (answer,) = Halver().run_command(HalveCommand(value=8))
    assert answer.result.value == 4
    with pytest.raises(CommandRefused):
        Halver().run_command(HalveCommand(value=-1))


def test_a_module_whose_answer_awaits_is_run_on_its_own_loop_from_plain_code():
    class Awaiting(Halver):
        async def ahandle(self, command: HalveCommand) -> Number:
            await asyncio.sleep(0)
            return Number(value=command.value * 10)

    command = HalveCommand(value=2)
    (answer,) = Awaiting().run_command(command)
    assert (answer.result.value, answer.request_id) == (20, command.request_id)


async def test_run_command_inside_a_loop_says_to_await_instead():
    class Awaiting(Halver):
        async def ahandle(self, command):
            return Number(value=1)

    with pytest.raises(RuntimeError, match="await arun_command"):
        Awaiting().run_command(HalveCommand(value=1))
    assert len(await Awaiting().arun_command(HalveCommand(value=1))) == 1


async def test_a_blocking_module_runs_in_a_thread():
    class Threaded(Doubler):
        blocking = True
        threads: list = []

        def process(self, message):
            Threaded.threads.append(threading.current_thread())
            return super().process(message)

    (result,) = await Threaded().arun(measurement(2))
    (inline,) = await Doubler().arun(measurement(2))
    assert result.result.value == inline.result.value == 4.0
    assert Threaded.threads[0] is not threading.main_thread()
    assert Threaded().run_one(measurement(1)).result.value == 2.0  # run() is always inline


# -- declaring a module ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("attributes", "match"),
    [
        ({"inputs": (Measurement, Alarm), "process": lambda self, m: None}, "needs an @on handler"),
        ({"inputs": (Measurement,)}, "no process"),
        ({"inputs": {"a": Measurement}, "process": lambda self, **k: None}, "needs a join"),
        ({"inputs": {"a": Measurement}, "join": Latest(trigger="b"), "process": lambda self, **k: None}, "trigger"),
        ({"inputs": (Measurement,), "join": Latest(trigger="a"), "process": lambda self, m: None}, "unnamed inputs"),
        ({"inputs": (Measurement,), "process": lambda self, m: None, "outputs": (Number,)}, "not a DataModel"),
        ({"inputs": (Measurement,), "process": lambda self, m: None, "outputs": (NumberResult, type("Other", (ResultEnvelope[Number],), {}))}, "both wrap Number"),
        ({"commands": (HalveCommand,)}, "neither handle"),
    ],
)
def test_a_module_that_does_not_add_up_is_refused_when_declared(attributes, match):
    with pytest.raises(TypeError, match=match):
        type("Bad", (Module,), attributes)


def test_an_on_handler_for_an_undeclared_input_is_refused():
    with pytest.raises(TypeError, match="not in its inputs"):

        class Bad(Module):
            inputs = (Measurement,)

            @on(Alarm)
            def on_alarm(self, alarm): ...


def test_a_module_lists_concrete_command_classes_only():
    with pytest.raises(ValueError, match="subclasses"):
        concrete_commands("M", (PlayerCommand,))
    assert concrete_commands("M", (HalveCommand,)) == (HalveCommand,)


# -- fed from a queue -------------------------------------------------------------------


async def test_a_module_publishes_one_envelope_per_result_and_reports_a_failure():
    inputs, out = queue(Measurement), Recorder()
    task = asyncio.create_task(serve_module(Doubler(), inputs, out))
    for message in (measurement(3), Measurement(value=-1, timestamp=at(4)), Measurement(value=1000, timestamp=at(5)), measurement(6)):
        inputs.offer(message)
    first, second = await out.wait_for(NumberResult, 2)
    (failure,) = await out.wait_for(ErrorEvent)
    await cancel_and_wait(task)
    assert (first.result.value, first.timestamp, first.app.name) == (6.0, at(3), "doubler")
    assert second.result.value == 12.0
    assert failure.source == "doubler" and failure.detail == "ValueError: too big"


async def test_a_result_that_does_not_fit_the_envelope_is_reported_and_the_next_input_is_read():
    inputs, out = queue(Measurement), Recorder()
    task = asyncio.create_task(serve_module(Doubler(), inputs, out))
    inputs.offer(Measurement(value=1))  # no timestamp, which the envelope requires
    inputs.offer(measurement(3))
    (failure,) = await out.wait_for(ErrorEvent)
    (result,) = await out.wait_for(NumberResult)
    await cancel_and_wait(task)
    assert failure.source == "doubler" and failure.detail.startswith("ValidationError")
    assert result.result.value == 6.0


async def test_an_undeclared_output_is_reported_and_the_next_input_is_read():
    class Sloppy(Doubler):
        def process(self, message):
            return Text(text="oops") if message.value == 1 else super().process(message)

    inputs, out = queue(Measurement), Recorder()
    task = asyncio.create_task(serve_module(Sloppy(), inputs, out))
    inputs.offer(measurement(1))
    inputs.offer(measurement(2))
    (failure,) = await out.wait_for(ErrorEvent)
    (result,) = await out.wait_for(NumberResult)
    await cancel_and_wait(task)
    assert failure.detail.startswith("UndeclaredOutput") and "Text" in failure.detail
    assert result.result.value == 4.0


# -- answering commands -----------------------------------------------------------------


async def test_a_command_is_answered_in_the_declared_envelope_with_its_request_id():
    commands, out = queue(HalveCommand), Recorder()
    inbox = command_inbox(Halver(), commands, out)
    inbox.start()
    command = HalveCommand(value=8)
    commands.offer(command)
    (result,) = await out.wait_for(NumberResult)
    await inbox.stop()
    assert result.result.value == 4 and result.request_id == command.request_id


async def test_a_refused_or_failed_command_is_an_error_event_with_its_request_id():
    commands, out = queue(HalveCommand), Recorder()
    inbox = command_inbox(Halver(), commands, out)
    inbox.start()
    refused, failing = HalveCommand(value=-1), HalveCommand(value=0)
    commands.offer(refused)
    commands.offer(failing)
    first, second = await out.wait_for(ErrorEvent, 2)
    await inbox.stop()
    assert (first.message, first.detail, first.request_id) == ("halver refused halve", "no negatives", refused.request_id)
    assert (second.detail, second.request_id) == ("RuntimeError: cannot halve zero", failing.request_id)
    assert out.of(NumberResult) == []


async def test_an_answer_that_cannot_be_published_is_reported_and_the_next_command_is_handled():
    class Misanswering(Halver):
        def handle(self, command: HalveCommand) -> BaseModel:
            return Measurement() if command.value == 1 else Number(value=command.value / 2)

    commands, out = queue(HalveCommand), Recorder()
    inbox = command_inbox(Misanswering(), commands, out)
    inbox.start()
    bad, good = HalveCommand(value=1), HalveCommand(value=8)
    commands.offer(bad)
    commands.offer(good)
    (failure,) = await out.wait_for(ErrorEvent)
    (result,) = await out.wait_for(NumberResult)
    await inbox.stop()
    assert (failure.message, failure.request_id) == ("halver applied halve but could not answer it", bad.request_id)
    assert failure.detail.startswith("UndeclaredOutput")
    assert (result.result.value, result.request_id) == (4, good.request_id)
