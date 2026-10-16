# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""How a command reaches the part that handles it.

A **receiver** (the player, or a module) lists the concrete ``Command``
classes it handles in ``commands``, checks one against its current state in
``validate`` (raising ``CommandRefused``), and applies it in ``handle``. A
command travels on its own topic, so routing a command is publishing it.

A ``CommandInbox`` applies one receiver's commands in order. It validates each
again before applying it, because the state may have changed since the command
was sent. A refusal or failure becomes an ``ErrorEvent`` carrying the command's
``request_id``. So does a command issued more than ``deadline`` seconds ago
(``CONTROL_DEADLINE_S``, by its ``timestamp``): held up by a broker outage, or
behind a slow command, it is reported rather than applied late. A command
of a ``preempt`` class does not wait: it stops the command in progress and
supersedes those queued before it, each reported (a source switch, away from
a source that hangs).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterable, Callable, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from pswamp_models.common import ErrorEvent

from .log import get_logger
from .transport import CONTROL_DEADLINE_S
from .util.tasks import cancel_and_wait
from .util.time import utcnow

if TYPE_CHECKING:
    from pswamp_models.common import Command

    from .subscription import Sink

__all__ = ["CommandInbox", "CommandReceiver", "CommandRefused", "NoReceiver", "concrete_commands"]

logger = get_logger("pswamp_core.command_routing")


class CommandRefused(Exception):
    """The command does not apply in the receiver's current state. The message
    says why, for a person."""


class NoReceiver(LookupError):
    """Nothing in the pipeline handles the command's class."""


class CommandReceiver(Protocol):
    name: str
    commands: ClassVar[tuple[type[Command], ...]]

    def validate(self, command: Command) -> None: ...

    async def handle(self, command: Command) -> object: ...


def concrete_commands(owner: str, commands: Sequence[type[Command]]) -> tuple[type[Command], ...]:
    """``commands``, checked to be concrete: a topic carries one class, so a
    base class would hear none of its subclasses."""
    for command in commands:
        if command.__subclasses__():
            raise ValueError(f"{owner} lists {command.__name__}, which has subclasses; list the concrete classes")
    return tuple(commands)


class CommandInbox:
    """Applies one receiver's commands, in order.

    Args:
        commands: Where the commands arrive.
        receiver: Who applies them.
        out: Where a refusal or failure is reported, as an ``ErrorEvent``.
        on_result: Called with a command and whatever non-``None`` ``handle``
            returned; a module publishes it as its result.
        deadline: A command issued longer ago than this is reported, not
            applied.
        preempt: Command classes that do not wait their turn: one stops the
            command in progress and supersedes those queued before it.
    """

    def __init__(
        self,
        commands: AsyncIterable[Command],
        receiver: CommandReceiver,
        out: Sink,
        *,
        on_result: Callable[[Command, Any], None] | None = None,
        deadline: float = CONTROL_DEADLINE_S,
        preempt: tuple[type[Command], ...] = (),
    ) -> None:
        self.receiver = receiver
        self._commands = commands
        self._out = out
        self._on_result = on_result
        self.deadline = deadline
        self.preempt = preempt
        self._task: asyncio.Task | None = None
        #: The command being applied, and its task, while the inbox reads ahead.
        self._applying: tuple[Command, asyncio.Task] | None = None
        self._preempted_by: Command | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._serve(), name=f"{self.receiver.name}.commands")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            await cancel_and_wait(task, ignore=(Exception,))  # a failure was logged in _serve

    async def _serve(self) -> None:
        try:
            if self.preempt:
                await self._serve_preempting()
            else:
                async for command in self._commands:
                    await self.apply(command)
        except Exception:
            logger.exception("%s stopped taking commands", self.receiver.name)
            raise

    async def _serve_preempting(self) -> None:
        """Apply in order, reading ahead meanwhile, so that a ``preempt``
        command can stop the one in progress."""
        waiting: deque[Command] = deque()
        wake = asyncio.Event()

        async def read() -> None:
            try:
                async for command in self._commands:
                    if isinstance(command, self.preempt):
                        while waiting:
                            self._superseded(waiting.popleft(), command, "did not apply")
                        if self._applying is not None:
                            self._preempted_by = command
                            self._applying[1].cancel()
                    waiting.append(command)
                    wake.set()
            finally:
                wake.set()

        reader = asyncio.create_task(read(), name=f"{self.receiver.name}.commands.read")
        try:
            while True:
                while not waiting:
                    if reader.done():
                        return await reader  # raises what ended it
                    wake.clear()
                    await wake.wait()
                command = waiting.popleft()
                applying = asyncio.create_task(self.apply(command), name=f"{self.receiver.name}.{command.name}")
                self._applying = (command, applying)
                try:
                    await applying
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if current is not None and current.cancelling():
                        raise
                    if self._preempted_by is not None:
                        self._superseded(command, self._preempted_by, "stopped applying")
                finally:
                    self._applying, self._preempted_by = None, None
        finally:
            await cancel_and_wait(reader, ignore=(Exception,))

    def _superseded(self, command: Command, by: Command, what: str) -> None:
        name = self.receiver.name
        logger.warning("%s %s %s (request %s): %s came after it", name, what, command.name, command.request_id, by.name)
        self._report(command, f"{name} {what} {command.name}: {by.name} came after it", f"a {by.name} replaces what came before it")

    async def apply(self, command: Command) -> None:
        """Validate and apply one command; report a refusal, a failure, or an
        answer that could not be published."""
        name = self.receiver.name
        age = None if command.timestamp is None else (utcnow() - command.timestamp).total_seconds()
        if age is not None and age > self.deadline:
            logger.warning("%s did not apply %s (request %s): issued %.1f s ago", name, command.name, command.request_id, age)
            self._report(
                command,
                f"{name} did not apply {command.name}: it arrived {age:.0f} s after it was issued",
                f"a command more than {self.deadline:g} s old is not applied, so that none is applied late",
            )
            return
        try:
            self.receiver.validate(command)
            result = await self.receiver.handle(command)
        except CommandRefused as refused:
            logger.warning("%s refused %s (request %s): %s", name, command.name, command.request_id, refused)
            self._report(command, f"{name} refused {command.name}", str(refused))
            return
        except Exception as error:
            logger.exception("%s failed to apply %s (request %s)", name, command.name, command.request_id)
            self._report(command, f"{name} failed to apply {command.name}", f"{type(error).__name__}: {error}")
            return
        logger.info("%s applied %s (request %s)", name, command.name, command.request_id)
        if result is None or self._on_result is None:
            return
        try:
            self._on_result(command, result)
        except Exception as error:
            logger.exception("%s could not answer %s (request %s)", name, command.name, command.request_id)
            self._report(
                command, f"{name} applied {command.name} but could not answer it", f"{type(error).__name__}: {error}"
            )

    def _report(self, command: Command, message: str, detail: str) -> None:
        self._out.publish(
            ErrorEvent(timestamp=utcnow(), source=self.receiver.name, message=message, detail=detail, request_id=command.request_id)
        )
