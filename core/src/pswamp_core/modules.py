# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Module``: read one message class, publish a result class.

A module declares what it reads (``input_model``) and what it publishes
(``output_model``, a ``ResultEnvelope`` subclass), and implements ``process``.
``run`` does the rest: read, call ``process``, wrap the returned body in the
envelope, publish it::

    class FrameStatsModule(Module):
        name = "frame-stats"
        input_model = PmuFrame
        output_model = FrameStatsResult

        async def process(self, frame: PmuFrame) -> FrameStats | None: ...

A module may also answer commands: it lists their concrete classes in
``commands`` and implements ``handle`` (and ``validate``, to refuse one). What
``handle`` returns is published like a ``process`` result, carrying the
command's ``request_id``. A module that only answers commands sets
``input_model = None``.

A module may also read data itself, a batch question over a range, say: it
sets ``reads_gateway = True`` and its host gives each instance a gateway of
its own (``self.gateway``) over the pipeline's sources, wherever it runs.

A module never sees the transport. A ``ModuleHost`` feeds it one run's input
and publishes what it emits (``pswamp_core.host``); whether the host is in the
server or in a worker is the deployment's choice. ``process`` runs on the
event loop: a module whose analysis blocks runs it in a thread or process pool.

**A module that falls behind says so.** Its ``KeepUpMonitor`` watches its
input queue, and past its ``keep_up`` policy reports an ``ErrorEvent``.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import AsyncIterable
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel

from .command_routing import CommandInbox
from .keep_up import KeepUp, KeepUpMonitor
from .log import get_logger
from .messages.errors import ErrorEvent
from .messages.results import AppIdentity, ResultEnvelope
from .subscription import Overflow
from .util.time import utcnow

if TYPE_CHECKING:
    from .datagateway import DataGateway
    from .messages.commands import Command
    from .messages.data_model import DataModel
    from .subscription import Sink, Subscription

__all__ = ["Module"]

logger = get_logger("pswamp_core.modules")


class Module(ABC):
    """Read ``input_model``; publish ``output_model``. See the module docstring.

    Class attributes:
        name: How the module identifies itself in results and error reports.
        input_model: The message class it reads; ``None`` for command-only.
        output_model: The ``ResultEnvelope`` subclass it publishes.
        commands: The concrete ``Command`` classes it answers.
        overflow, maxsize: Its input queue. ``DROP_OLDEST`` by default: a
            module that falls behind a live stream analyses the newest frame.
        reads_gateway: Its host sets ``self.gateway`` before ``setup``.
        keep_up: When falling behind its input is reported; ``None`` never.
    """

    name: ClassVar[str] = "module"
    input_model: ClassVar[type[DataModel] | None]
    output_model: ClassVar[type[ResultEnvelope]]
    commands: ClassVar[tuple[type[Command], ...]] = ()
    overflow: ClassVar[Overflow] = Overflow.DROP_OLDEST
    maxsize: ClassVar[int] = 64
    reads_gateway: ClassVar[bool] = False
    keep_up: ClassVar[KeepUp | None] = KeepUp()

    def __init__(self) -> None:
        self.identity = AppIdentity(name=self.name, uuid=uuid4().hex)
        #: Settings recorded on every result.
        self.parameters: dict[str, Any] = {}
        #: The pipeline's sources, for a module that ``reads_gateway``.
        self.gateway: DataGateway | None = None
        what = f"is not keeping up with {self.input_model.topic}" if self.input_model else ""
        self.monitor = KeepUpMonitor(self.name, what, self.keep_up if self.input_model else None)

    async def setup(self, out: Sink) -> None:
        """Called once before ``run``. ``out`` is where to publish anything
        outside ``process``: a command to the player, say."""

    async def process(self, message: DataModel) -> BaseModel | None:
        """Analyse one input. Return the result body, or ``None`` for nothing."""
        raise NotImplementedError(f"{type(self).__name__} has an input_model but no process()")

    def validate(self, command: Command) -> None:
        """Raise ``CommandRefused`` if ``command`` does not apply now."""

    async def handle(self, command: Command) -> BaseModel | None:
        """Answer one of ``commands``: the result body, or ``None``."""
        raise NotImplementedError(f"{type(self).__name__} lists commands but has no handle()")

    def wrap(self, body: BaseModel, *, timestamp: datetime, request_id: str | None = None) -> ResultEnvelope:
        """``body`` in this module's envelope."""
        return self.output_model(
            timestamp=timestamp, app=self.identity, parameters=self.parameters, request_id=request_id, result=body
        )

    def command_inbox(self, commands: AsyncIterable[Command], out: Sink) -> CommandInbox:
        """Applies this module's commands; answers and refusals go to ``out``."""

        def answer(command: Command, body: BaseModel) -> None:
            out.publish(self.wrap(body, timestamp=utcnow(), request_id=command.request_id))

        return CommandInbox(commands, self, out, on_result=answer)

    async def run(self, inputs: Subscription, out: Sink) -> None:
        """Read and process until cancelled. A failing ``process``, or a result
        that does not fit the envelope, is logged, reported as an
        ``ErrorEvent``, and the next input is read."""
        if self.input_model is None:
            return
        async for message in inputs:
            try:
                self.monitor.observe(inputs, message, out)
                result = await self.process(message)
                if result is not None:
                    out.publish(self.wrap(result, timestamp=message.timestamp))
            except Exception as error:
                logger.exception("module %s failed on %s", self.name, type(message).__name__)
                out.publish(
                    ErrorEvent(
                        timestamp=utcnow(),
                        source=self.name,
                        message=f"module {self.name} failed on {type(message).__name__}",
                        detail=f"{type(error).__name__}: {error}",
                    )
                )
