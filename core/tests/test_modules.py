"""A module reads its input queue and publishes its result envelope; its
commands come through its inbox."""

from __future__ import annotations

import asyncio
from typing import Literal

import pytest
from pydantic import BaseModel
from support import Measurement, Number, NumberResult, Recorder, at, frame, measurement, placed, queue

from pswamp_core.command_routing import CommandRefused, concrete_commands
from pswamp_core.messages import Command, ErrorEvent, PlayerCommand, PmuFrame
from pswamp_core.modules import Module
from pswamp_core.util.tasks import cancel_and_wait


class Doubler(Module):
    name = "doubler"
    input_model = Measurement
    output_model = NumberResult

    async def process(self, message: Measurement) -> Number | None:
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
    input_model = None
    output_model = NumberResult
    commands = (HalveCommand,)

    def validate(self, command: HalveCommand) -> None:
        if command.value < 0:
            raise CommandRefused("no negatives")

    async def handle(self, command: HalveCommand) -> Number:
        if command.value == 0:
            raise RuntimeError("cannot halve zero")
        return Number(value=command.value / 2)


async def test_a_module_publishes_one_envelope_per_result_and_reports_a_failure():
    inputs, out = queue(Measurement), Recorder()
    task = asyncio.create_task(Doubler().run(inputs, out))
    for message in (measurement(3), Measurement(value=-1, timestamp=at(4)), Measurement(value=1000, timestamp=at(5)), measurement(6)):
        inputs.offer(message)
    first, second = await out.wait_for(NumberResult, 2)
    (failure,) = await out.wait_for(ErrorEvent)
    await cancel_and_wait(task)
    assert (first.result.value, first.timestamp, first.app.name) == (6.0, at(3), "doubler")
    assert second.result.value == 12.0
    assert failure.source == "doubler" and failure.detail == "ValueError: too big"


async def test_a_command_is_answered_in_the_output_model_with_its_request_id():
    commands, out = queue(HalveCommand), Recorder()
    inbox = Halver().command_inbox(commands, out)
    inbox.start()
    command = HalveCommand(value=8)
    commands.offer(command)
    (result,) = await out.wait_for(NumberResult)
    await inbox.stop()
    assert result.result.value == 4 and result.request_id == command.request_id


async def test_a_refused_or_failed_command_is_an_error_event_with_its_request_id():
    commands, out = queue(HalveCommand), Recorder()
    inbox = Halver().command_inbox(commands, out)
    inbox.start()
    refused, failing = HalveCommand(value=-1), HalveCommand(value=0)
    commands.offer(refused)
    commands.offer(failing)
    first, second = await out.wait_for(ErrorEvent, 2)
    await inbox.stop()
    assert (first.message, first.detail, first.request_id) == ("halver refused halve", "no negatives", refused.request_id)
    assert (second.detail, second.request_id) == ("RuntimeError: cannot halve zero", failing.request_id)
    assert out.of(NumberResult) == []


async def test_a_result_that_does_not_fit_the_envelope_is_reported_and_the_next_input_is_read():
    inputs, out = queue(Measurement), Recorder()
    task = asyncio.create_task(Doubler().run(inputs, out))
    inputs.offer(Measurement(value=1))  # no timestamp, which the envelope requires
    inputs.offer(measurement(3))
    (failure,) = await out.wait_for(ErrorEvent)
    (result,) = await out.wait_for(NumberResult)
    await cancel_and_wait(task)
    assert failure.source == "doubler" and failure.detail.startswith("ValidationError")
    assert result.result.value == 6.0


async def test_an_answer_that_does_not_fit_the_envelope_is_reported_and_the_next_command_is_handled():
    class Misanswering(Halver):
        async def handle(self, command: HalveCommand) -> BaseModel:
            return Measurement() if command.value == 1 else Number(value=command.value / 2)

    commands, out = queue(HalveCommand), Recorder()
    inbox = Misanswering().command_inbox(commands, out)
    inbox.start()
    bad, good = HalveCommand(value=1), HalveCommand(value=8)
    commands.offer(bad)
    commands.offer(good)
    (failure,) = await out.wait_for(ErrorEvent)
    (result,) = await out.wait_for(NumberResult)
    await inbox.stop()
    assert (failure.message, failure.request_id) == ("halver applied halve but could not answer it", bad.request_id)
    assert (result.result.value, result.request_id) == (4, good.request_id)


def test_a_module_lists_concrete_command_classes_only():
    with pytest.raises(ValueError, match="subclasses"):
        concrete_commands("M", (PlayerCommand,))
    assert concrete_commands("M", (HalveCommand,)) == (HalveCommand,)


# --- a module with a window: breaks, reset, the warm-up -------------------------------


class Window(Module):
    """Counts the frames in its window, and needs 0.1 s of them (three at 20 Hz)."""

    name = "window"
    input_model = PmuFrame
    output_model = NumberResult
    warm_up_s = 0.1

    def __init__(self) -> None:
        super().__init__()
        self.window: list[PmuFrame] = []
        self.calls = self.resets = 0

    def reset(self) -> None:
        self.resets += 1
        self.window.clear()

    async def process(self, frame: PmuFrame) -> Number:
        self.calls += 1
        self.window.append(frame)
        return Number(value=len(self.window))


async def through(module: Window, frames: list[PmuFrame]) -> list[NumberResult]:
    """Run ``frames`` through ``module`` and return what it published."""
    inputs, out = queue(PmuFrame), Recorder()
    task = asyncio.create_task(module.run(inputs, out))
    for one in frames:
        inputs.offer(one)

    async def all_read():
        while module.calls < len(frames):
            await asyncio.sleep(0.005)

    await asyncio.wait_for(all_read(), 5)
    await cancel_and_wait(task)
    assert out.of(ErrorEvent) == []
    return out.of(NumberResult)


async def test_a_result_carries_the_stream_of_its_input():
    class Every(Window):
        warm_up_s = 0.0

    (result,) = await through(Every(), [placed(0, "a", 0)])
    assert result.stream == "a"
    (plain,) = await through(Every(), [frame(0)])  # a frame built by hand has no place
    assert plain.stream is None


async def test_reset_is_called_when_the_input_breaks_and_never_before_the_first_input():
    module = Window()
    await through(module, [placed(0, "a", 0)])
    assert module.resets == 0
    module = Window()
    await through(
        module,
        [
            placed(0.00, "a", 0), placed(0.05, "a", 1),
            placed(1.00, "b", 0), placed(1.05, "b", 1),  # another stream: a seek, a loop, a switch
            placed(1.15, "b", 3),  # number 2 never came: a frame went missing
        ],
    )
    assert module.resets == 2
    assert [f.timestamp for f in module.window] == [at(1.15)]


async def test_results_are_held_back_for_the_warm_up_after_every_break():
    module = Window()
    frames = [
        placed(0.00, "a", 0), placed(0.05, "a", 1), placed(0.10, "a", 2), placed(0.15, "a", 3),
        placed(1.00, "b", 0), placed(1.05, "b", 1), placed(1.10, "b", 2),
        placed(1.20, "b", 4), placed(1.25, "b", 5), placed(1.30, "b", 6),  # number 3 is missing
    ]
    published = await through(module, frames)
    assert module.calls == len(frames)  # every input is processed, so the window fills
    assert [r.timestamp for r in published] == [at(0.10), at(0.15), at(1.10), at(1.30)]
    assert [r.result.value for r in published] == [3, 4, 3, 3]  # a full window each time
    assert [r.stream for r in published] == ["a", "a", "b", "b"]


async def test_frames_without_a_place_are_one_unbroken_run():
    module = Window()
    published = await through(module, [frame(i / 20) for i in range(5)])
    assert module.resets == 0
    assert [r.timestamp for r in published] == [at(0.10), at(0.15), at(0.20)]
