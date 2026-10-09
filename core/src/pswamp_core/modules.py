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

**A module that needs several inputs before it can answer** (a window) says
so with two attributes and one method. All three are off unless set::

    class RollingMeanModule(Module):
        warm_up_s = 5.0             # seconds of unbroken input before an answer counts
        cache_results = True        # the same inputs always give the same result

        def reset(self) -> None:    # the input is no longer continuous
            self._window.clear()

- ``warm_up_s``: how many seconds of unbroken input the analysis needs before
  its answer counts. 0 means every input gives an answer on its own. While
  the module warms up, ``process`` is still called with every input, so it
  can fill its window, but what it returns is not published. The warm-up
  starts at the module's first input and starts again after every break (see
  ``reset``). It is counted in the data's own time, not on the clock.
- ``cache_results``: set it to ``True`` to let the server keep this module's
  results for a recording and show them again when any client is at the same
  instant. Setting it is a promise: the same inputs always give the same
  result. So a result depends only on the recording and the instant, never on
  the client, on a command, on the clock, on chance, or on anything else
  outside the inputs. Leave it ``False``, the default, for an analysis that
  is not deterministic. Nothing checks this promise: a result kept from an
  earlier replay is shown in place of what the module would have computed
  this time.
- ``reset()``: called when the input stops being continuous: the player moved
  (a seek, a step back, a loop, another source) or a frame went missing.
  Throw away everything built from earlier inputs, the window above all. Keep
  settings. It is not called before the first input, and a module never calls
  it itself.

``run`` knows a break from the inputs themselves: a frame carries the stream
it was read in and its number there (``PmuFrame.stream``, ``seq``). Every
result carries its input's ``stream`` on.
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
        warm_up_s: Seconds of unbroken input before a result counts; until
            then ``process`` is called and what it returns is not published.
        cache_results: ``True`` promises the same inputs always give the same
            result, so the server may keep a recording's results and show
            them again. Leave ``False`` for an analysis that is not
            deterministic.
    """

    name: ClassVar[str] = "module"
    input_model: ClassVar[type[DataModel] | None]
    output_model: ClassVar[type[ResultEnvelope]]
    commands: ClassVar[tuple[type[Command], ...]] = ()
    overflow: ClassVar[Overflow] = Overflow.DROP_OLDEST
    maxsize: ClassVar[int] = 64
    reads_gateway: ClassVar[bool] = False
    keep_up: ClassVar[KeepUp | None] = KeepUp()
    warm_up_s: ClassVar[float] = 0.0
    cache_results: ClassVar[bool] = False

    def __init__(self) -> None:
        self.identity = AppIdentity(name=self.name, uuid=uuid4().hex)
        #: Settings recorded on every result.
        self.parameters: dict[str, Any] = {}
        #: The pipeline's sources, for a module that ``reads_gateway``.
        self.gateway: DataGateway | None = None
        what = f"is not keeping up with {self.input_model.topic}" if self.input_model else ""
        self.monitor = KeepUpMonitor(self.name, what, self.keep_up if self.input_model else None)
        #: The last input's place (its stream and number there), and the
        #: timestamp of the input the current unbroken run began with.
        self._stream: str | None = None
        self._seq: int | None = None
        self._unbroken_since: datetime | None = None
        self._read_any = False

    async def setup(self, out: Sink) -> None:
        """Called once before ``run``. ``out`` is where to publish anything
        outside ``process``: a command to the player, say."""

    async def process(self, message: DataModel) -> BaseModel | None:
        """Analyse one input. Return the result body, or ``None`` for nothing."""
        raise NotImplementedError(f"{type(self).__name__} has an input_model but no process()")

    def reset(self) -> None:
        """Throw away everything built from earlier inputs, the window above
        all. Keep settings.

        ``run`` calls it when the input stops being continuous: the player
        moved (a seek, a step back, a loop, another source) or a frame went
        missing. It is not called before the first input, and a module never
        calls it itself. The default does nothing: right for a module that
        answers from one input."""

    def validate(self, command: Command) -> None:
        """Raise ``CommandRefused`` if ``command`` does not apply now."""

    async def handle(self, command: Command) -> BaseModel | None:
        """Answer one of ``commands``: the result body, or ``None``."""
        raise NotImplementedError(f"{type(self).__name__} lists commands but has no handle()")

    def wrap(
        self, body: BaseModel, *, timestamp: datetime, request_id: str | None = None, stream: str | None = None
    ) -> ResultEnvelope:
        """``body`` in this module's envelope."""
        return self.output_model(
            timestamp=timestamp,
            app=self.identity,
            parameters=self.parameters,
            request_id=request_id,
            stream=stream,
            result=body,
        )

    def _warming_up(self, message: DataModel) -> bool:
        """Note ``message``'s place in its stream; ``True`` while a result
        from it does not count yet.

        The first input starts the warm-up. A break is an input from
        another stream, or one whose number does not follow the last: at a
        break ``reset`` is called, and the warm-up starts again from that
        input."""
        stream, seq = getattr(message, "stream", None), getattr(message, "seq", None)
        skipped = seq is not None and self._seq is not None and seq != self._seq + 1
        if not self._read_any or stream != self._stream or skipped:
            if self._read_any:
                self.reset()
            self._read_any = True
            self._unbroken_since = message.timestamp
        self._stream, self._seq = stream, seq
        if self.warm_up_s <= 0:
            return False
        return (message.timestamp - self._unbroken_since).total_seconds() < self.warm_up_s

    def command_inbox(self, commands: AsyncIterable[Command], out: Sink) -> CommandInbox:
        """Applies this module's commands; answers and refusals go to ``out``."""

        def answer(command: Command, body: BaseModel) -> None:
            out.publish(self.wrap(body, timestamp=utcnow(), request_id=command.request_id))

        return CommandInbox(commands, self, out, on_result=answer)

    async def run(self, inputs: Subscription, out: Sink) -> None:
        """Read and process until cancelled. A failing ``process``, or a result
        that does not fit the envelope, is logged, reported as an
        ``ErrorEvent``, and the next input is read.

        Every input is processed; a result is published unless the module is
        still warming up (``warm_up_s``). ``reset`` is called when the input
        breaks: it comes from another stream, or a frame is missing."""
        if self.input_model is None:
            return
        async for message in inputs:
            try:
                self.monitor.observe(inputs, message, out)
                warming_up = self._warming_up(message)
                result = await self.process(message)
                if result is not None and not warming_up:
                    stream = getattr(message, "stream", None)
                    out.publish(self.wrap(result, timestamp=message.timestamp, stream=stream))
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
