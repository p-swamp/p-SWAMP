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
``request_id``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable, Sequence
from typing import TYPE_CHECKING, ClassVar, Protocol

from .log import get_logger
from .messages.errors import ErrorEvent
from .util.tasks import cancel_and_wait
from .util.time import utcnow

if TYPE_CHECKING:
    from pydantic import BaseModel

    from .messages.commands import Command
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

    async def handle(self, command: Command) -> BaseModel | None: ...


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
    """

    def __init__(
        self,
        commands: AsyncIterable[Command],
        receiver: CommandReceiver,
        out: Sink,
        *,
        on_result: Callable[[Command, BaseModel], None] | None = None,
    ) -> None:
        self.receiver = receiver
        self._commands = commands
        self._out = out
        self._on_result = on_result
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._serve(), name=f"{self.receiver.name}.commands")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            await cancel_and_wait(task, ignore=(Exception,))  # a failure was logged in _serve

    async def _serve(self) -> None:
        try:
            async for command in self._commands:
                await self.apply(command)
        except Exception:
            logger.exception("%s stopped taking commands", self.receiver.name)
            raise

    async def apply(self, command: Command) -> None:
        """Validate and apply one command; report a refusal, a failure, or an
        answer that could not be published."""
        name = self.receiver.name
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
