# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Module``: declared inputs in, declared outputs out, synchronous code between.

A module declares the message classes it reads (``inputs``) and the ones it
publishes (``outputs``), and implements ``process``, a plain synchronous
method. It reads its inputs in one of three styles::

    # 1. One input: the common case.
    class FrameStatsModule(Module):
        name = "frame-stats"
        inputs = (PmuFrame,)
        outputs = (FrameStatsResult,)

        def process(self, frame: PmuFrame) -> FrameStats | None: ...

    # 2. Independent inputs: one handler each; the module keeps any state.
    class Monitor(Module):
        inputs = (PmuFrame, AlarmEvent)
        outputs = (MonitorResult,)

        @on(PmuFrame)
        def on_frame(self, frame): ...

        @on(AlarmEvent)
        def on_alarm(self, alarm): ...

    # 3. Simultaneous inputs: named, and combined by a join into one call.
    class Assessment(Module):
        inputs = {"pmu": PmuFrame, "scada": ScadaSnapshot, "se": StateEstimate}
        join = Latest(trigger="se", max_age={"pmu": 1.0, "scada": 10.0}, missing="skip")
        outputs = (AssessmentResult,)

        def process(self, *, pmu, scada, se) -> Assessment: ...

(``on`` and ``Latest`` are in ``pswamp_core.inputs``, re-exported here.)

**What a handler returns** is one message, a list of them, or ``None``. A
result *body* is wrapped in the declared ``ResultEnvelope[T]`` whose ``T`` it
is (``FrameStats`` → ``FrameStatsResult``), stamped with the input's
timestamp. Anything else declared in ``outputs`` (an envelope built by hand, a
command for another part of the pipeline) is published as it is. A message of
an undeclared class is an error: there is no other way to publish.

A module may also answer commands: it lists their concrete classes in
``commands``, implements ``handle`` (synchronous too, returning what
``process`` would) and, to refuse one, ``validate``. A module whose answer
must await (reading history through its sources, say) implements ``ahandle``
instead. An answer carries the command's ``request_id``.

**Calling a module.** ``run`` is the synchronous call, for a script or a test,
and returns exactly what a host would publish::

    stats = FrameStatsModule()
    stats.run_one(frame).result.mean_frequency_hz

``run(frame)`` for styles 1 and 2; ``run(pmu=f, scada=s, se=e)`` for style 3,
which bypasses the join. ``run_command`` answers a command the same way.
``await arun(message)`` and ``await arun_command(command)`` are what a
``ModuleHost`` calls; with ``blocking = True`` they run the module's code in a
thread, off the event loop.

A module never sees the transport. A ``ModuleHost`` feeds it one run's input
and publishes its outputs (``pswamp_core.host``); whether the host is in the
server or in a worker is the deployment's choice.

A module may also read data itself, a batch question over a range, say: it
sets ``reads_sources = True`` and its host gives each instance a ``SourceSet``
of its own (``self.sources``) over the pipeline's sources, wherever it runs.
"""

from __future__ import annotations

import asyncio
from abc import ABC
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel

from pswamp_models.common import AppIdentity, Command, DataModel, ResultEnvelope

from .inputs import Latest, handlers_of, on
from .keep_up import KeepUp
from .subscription import Overflow
from .util.time import utcnow

if TYPE_CHECKING:
    from .sources import SourceSet

__all__ = ["Latest", "Module", "UndeclaredOutput", "on"]


class UndeclaredOutput(TypeError):
    """A handler returned a message of a class its module does not declare."""


class Module(ABC):
    """Declared inputs in, declared outputs out. See the module docstring.

    Class attributes:
        name: How the module identifies itself in results and error reports.
        inputs: The message classes it reads: a tuple (styles 1 and 2), or a
            dict of name → class with a ``join`` (style 3). ``()`` for a
            module that only answers commands.
        join: How named inputs are combined (``Latest``); only with a dict.
        outputs: The classes it publishes: ``ResultEnvelope`` subclasses its
            bodies are wrapped in, and anything it sends as it is (a command).
        commands: The concrete ``Command`` classes it answers.
        blocking: Run ``process`` and ``handle`` in a thread when hosted.
        overflow, maxsize: Its input queue (the trigger's, with a join).
            ``DROP_OLDEST`` by default: a module that falls behind a live
            stream analyses the newest frame.
        reads_sources: Its host sets ``self.sources`` before ``setup``.
        keep_up: When falling behind its input is reported; ``None`` never.
    """

    name: ClassVar[str] = "module"
    inputs: ClassVar[tuple[type[DataModel], ...] | Mapping[str, type[DataModel]]] = ()
    join: ClassVar[Latest | None] = None
    outputs: ClassVar[tuple[type[DataModel], ...]] = ()
    commands: ClassVar[tuple[type[Command], ...]] = ()
    blocking: ClassVar[bool] = False
    overflow: ClassVar[Overflow] = Overflow.DROP_OLDEST
    maxsize: ClassVar[int] = 64
    reads_sources: ClassVar[bool] = False
    keep_up: ClassVar[KeepUp | None] = KeepUp()

    #: Set per class: input class → handler method name (styles 1 and 2).
    _handlers: ClassVar[dict[type[DataModel], str]] = {}
    #: Set per class: result body class → the envelope it is wrapped in.
    _envelopes: ClassVar[dict[type[BaseModel], type[ResultEnvelope]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._check_inputs()
        cls._envelopes = cls._check_outputs()
        if cls.commands and not cls._overrides("handle", "ahandle"):
            raise TypeError(f"{cls.__name__} lists commands but implements neither handle() nor ahandle()")

    # -- class declaration -----------------------------------------------------------

    @classmethod
    def _overrides(cls, *names: str) -> bool:
        return any(getattr(cls, name) is not getattr(Module, name) for name in names)

    @classmethod
    def _check_inputs(cls) -> None:
        owner = cls.__name__
        handlers = handlers_of(cls)
        if isinstance(cls.inputs, Mapping):
            if not isinstance(cls.join, Latest):
                raise TypeError(f"{owner} names its inputs, so it needs a join, e.g. join = Latest(trigger=...)")
            if handlers:
                raise TypeError(f"{owner} joins its inputs into one process() call; @on does not apply")
            for model in cls.inputs.values():
                _require_model(owner, "inputs", model)
            cls.join.check(cls.inputs, owner)
            if not cls._overrides("process"):
                raise TypeError(f"{owner} has inputs but no process()")
            cls._handlers = {}
            return
        if not isinstance(cls.inputs, tuple):
            raise TypeError(f"{owner}.inputs must be a tuple of message classes, or a dict with a join")
        if cls.join is not None:
            raise TypeError(f"{owner} has a join but unnamed inputs; name them: inputs = {{'name': Model, ...}}")
        for model in cls.inputs:
            _require_model(owner, "inputs", model)
        if len(set(cls.inputs)) != len(cls.inputs):
            raise TypeError(f"{owner} lists an input twice")
        extra = [model.__name__ for model in handlers if model not in cls.inputs]
        if extra:
            raise TypeError(f"{owner} has @on handlers for {extra}, which are not in its inputs")
        if len(cls.inputs) > 1 or handlers:
            missing = [model.__name__ for model in cls.inputs if model not in handlers]
            if missing:
                raise TypeError(f"{owner} reads several inputs, so each needs an @on handler; none for {missing}")
            cls._handlers = dict(handlers)
        elif cls.inputs:
            if not cls._overrides("process"):
                raise TypeError(f"{owner} has inputs but no process()")
            cls._handlers = {cls.inputs[0]: "process"}
        else:
            cls._handlers = {}

    @classmethod
    def _check_outputs(cls) -> dict[type[BaseModel], type[ResultEnvelope]]:
        owner = cls.__name__
        if not isinstance(cls.outputs, tuple):
            raise TypeError(f"{owner}.outputs must be a tuple of message classes")
        envelopes: dict[type[BaseModel], type[ResultEnvelope]] = {}
        for model in cls.outputs:
            _require_model(owner, "outputs", model)
            if not issubclass(model, ResultEnvelope):
                continue
            body = _body_of(model)
            if body is None:
                raise TypeError(f"{owner}: {model.__name__} does not say its body: subclass ResultEnvelope[YourBody]")
            if body in envelopes:
                raise TypeError(
                    f"{owner}: {envelopes[body].__name__} and {model.__name__} both wrap {body.__name__}, "
                    f"so a {body.__name__} could go in either"
                )
            envelopes[body] = model
        return envelopes

    @classmethod
    def input_models(cls) -> tuple[type[DataModel], ...]:
        """Every class the module reads, however it reads them."""
        return tuple(cls.inputs.values()) if isinstance(cls.inputs, Mapping) else cls.inputs

    @classmethod
    def queued_inputs(cls) -> tuple[type[DataModel], ...]:
        """The inputs a host queues: all of them, or only a join's trigger. The
        others only replace the newest of their input (``observe``)."""
        if isinstance(cls.inputs, Mapping):
            return (cls.inputs[cls.join.trigger],)
        return cls.inputs

    # -- an instance -------------------------------------------------------------------

    def __init__(self) -> None:
        self.identity = AppIdentity(name=self.name, uuid=uuid4().hex)
        #: Settings recorded on every result.
        self.parameters: dict[str, Any] = {}
        #: The pipeline's sources, for a module that ``reads_sources``.
        self.sources: SourceSet | None = None
        #: This instance's join state, for named inputs.
        self._join = type(self).join.bound(self.inputs) if isinstance(self.inputs, Mapping) else None

    async def setup(self) -> None:
        """Called once by a host, after ``sources`` is set and before any input."""

    def process(self, *args: Any, **named: Any) -> Any:
        """Analyse one input (or one bundle, by name). Return a body, a
        declared message, a list of them, or ``None`` for nothing."""
        raise NotImplementedError(f"{type(self).__name__} has no process()")

    def validate(self, command: Command) -> None:
        """Raise ``CommandRefused`` if ``command`` does not apply now."""

    def handle(self, command: Command) -> Any:
        """Answer one of ``commands``, as ``process`` answers an input."""
        raise NotImplementedError(f"{type(self).__name__} lists commands but has no handle()")

    async def ahandle(self, command: Command) -> Any:
        """``handle``, for a module whose answer must await. By default it
        calls ``handle`` (in a thread if ``blocking``)."""
        return await self._call(self.handle, command)

    # -- calling it --------------------------------------------------------------------

    def run(self, message: DataModel | None = None, /, **named: DataModel | None) -> list[DataModel]:
        """Process one input synchronously; what a host would publish for it.

        ``run(message)`` dispatches on its class (and, for named inputs, feeds
        the join as a host would). ``run(name=message, ...)`` calls a joined
        ``process`` directly, bypassing the join."""
        call = self._prepare(message, named)
        if call is None:
            return []
        handler, args, kwargs, timestamp = call
        return self.outputs_of(handler(*args, **kwargs), timestamp=timestamp)

    def run_one(self, message: DataModel | None = None, /, **named: DataModel | None) -> DataModel:
        """``run``, for exactly one output; ``ValueError`` otherwise."""
        outputs = self.run(message, **named)
        if len(outputs) != 1:
            raise ValueError(f"{self.name} published {len(outputs)} messages, not one: {[type(o).__name__ for o in outputs]}")
        return outputs[0]

    async def arun(self, message: DataModel) -> list[DataModel]:
        """``run`` for one arriving message, as a host calls it: the module's
        code runs inline, or in a thread if ``blocking``."""
        call = self._prepare(message, {})
        if call is None:
            return []
        handler, args, kwargs, timestamp = call
        return self.outputs_of(await self._call(handler, *args, **kwargs), timestamp=timestamp)

    def observe(self, message: DataModel) -> None:
        """Take a non-trigger input of a join: it only replaces that input's
        newest message. What a host does instead of queueing it."""
        if self._join is None:
            raise TypeError(f"{self.name} has no join")
        self._join.feed(message)

    def run_command(self, command: Command) -> list[DataModel]:
        """Validate and answer ``command`` synchronously. A module that
        implements ``ahandle`` is run on a fresh event loop, so not from
        inside a running one: there, ``await arun_command(command)``."""
        self.validate(command)
        if self._overrides("ahandle"):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                answer = asyncio.run(self.ahandle(command))
            else:
                raise RuntimeError(f"{self.name} answers asynchronously; inside an event loop, await arun_command()")
        else:
            answer = self.handle(command)
        return self.answer_of(command, answer)

    async def arun_command(self, command: Command) -> list[DataModel]:
        """Validate and answer ``command``."""
        self.validate(command)
        return self.answer_of(command, await self.ahandle(command))

    # -- outputs -----------------------------------------------------------------------

    def outputs_of(
        self, returned: Any, *, timestamp: datetime | None, request_id: str | None = None
    ) -> list[DataModel]:
        """What a handler returned, as the messages to publish: bodies wrapped
        in their envelope, declared messages as they are. ``UndeclaredOutput``
        for anything else; a ``ValidationError`` for a body that does not fit."""
        if returned is None:
            return []
        items = returned if isinstance(returned, (list, tuple)) else [returned]
        return [self._output(item, timestamp, request_id) for item in items if item is not None]

    def answer_of(self, command: Command, returned: Any) -> list[DataModel]:
        """``outputs_of`` for an answer to ``command``: stamped now, carrying
        its ``request_id``."""
        return self.outputs_of(returned, timestamp=utcnow(), request_id=command.request_id)

    def wrap(self, body: BaseModel, *, timestamp: datetime | None, request_id: str | None = None) -> ResultEnvelope:
        """``body`` in the envelope this module declares for its class."""
        envelope = self._envelope_for(body)
        if envelope is None:
            raise UndeclaredOutput(f"{self.name} declares no ResultEnvelope[{type(body).__name__}] in its outputs")
        return envelope(timestamp=timestamp, app=self.identity, parameters=self.parameters, request_id=request_id, result=body)

    def _output(self, item: Any, timestamp: datetime | None, request_id: str | None) -> DataModel:
        if type(item) in self.outputs:
            return item
        if isinstance(item, BaseModel) and self._envelope_for(item) is not None:
            return self.wrap(item, timestamp=timestamp, request_id=request_id)
        declared = ", ".join(model.__name__ for model in self.outputs) or "nothing"
        raise UndeclaredOutput(
            f"{self.name} returned a {type(item).__name__}, which is not in its outputs ({declared}) "
            f"nor the body of one of them"
        )

    def _envelope_for(self, body: BaseModel) -> type[ResultEnvelope] | None:
        envelope = self._envelopes.get(type(body))
        if envelope is not None:
            return envelope
        matches = [env for cls, env in self._envelopes.items() if isinstance(body, cls)]
        return matches[0] if len(matches) == 1 else None

    # -- dispatch ----------------------------------------------------------------------

    def _prepare(
        self, message: DataModel | None, named: dict[str, DataModel | None]
    ) -> tuple[Callable[..., Any], tuple, dict, datetime | None] | None:
        """The handler to call for ``message`` (or the named bundle), its
        arguments and the timestamp of its outputs; ``None`` for no call."""
        if self._join is not None:
            if message is not None and named:
                raise TypeError(f"{self.name}: pass one message, or the inputs by name, not both")
            if message is None:
                unknown = sorted(set(named) - set(self.inputs))
                if unknown or self._join.trigger not in named:
                    raise TypeError(f"{self.name}.run() takes {sorted(self.inputs)} by name, with {self._join.trigger!r}")
                bundle: dict[str, DataModel | None] | None = {name: named.get(name) for name in self.inputs}
            else:
                bundle = self._join.feed(message)
            if bundle is None:
                return None
            trigger = bundle[self._join.trigger]
            return self.process, (), bundle, None if trigger is None else trigger.timestamp
        if named or message is None:
            raise TypeError(f"{self.name}.run() takes one message: one of {[m.__name__ for m in self.inputs]}")
        name = self._handlers.get(type(message))
        if name is None:
            raise TypeError(f"{self.name} does not read {type(message).__name__}")
        return getattr(self, name), (message,), {}, message.timestamp

    async def _call(self, handler: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self.blocking:
            return await asyncio.to_thread(handler, *args, **kwargs)
        return handler(*args, **kwargs)


def _require_model(owner: str, where: str, model: object) -> None:
    if not (isinstance(model, type) and issubclass(model, DataModel)):
        raise TypeError(f"{owner}.{where} lists {model!r}, which is not a DataModel class")


def _body_of(envelope: type[ResultEnvelope]) -> type[BaseModel] | None:
    """The ``T`` of a ``ResultEnvelope[T]`` subclass."""
    annotation = envelope.model_fields["result"].annotation
    return annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None
