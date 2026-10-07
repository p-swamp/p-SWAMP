# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""How a module's inputs reach its code: ``@on`` and the ``Latest`` join.

A module reads its inputs in one of three styles (``pswamp_core.modules``).
Two of them need a helper, and both are here, plain and synchronous, so they
can be tested without a loop or a transport:

- **Independent inputs**, each with its own handler::

      @on(PmuFrame)
      def on_frame(self, frame: PmuFrame): ...

  ``on`` only marks the method; ``handlers_of`` finds the marks on a class.

- **Simultaneous inputs**, named and combined into one call by a join::

      inputs = {"pmu": PmuFrame, "scada": ScadaSnapshot, "se": StateEstimate}
      join = Latest(trigger="se", max_age={"pmu": 1.0, "scada": 10.0}, missing="skip")

  ``Latest`` keeps the newest message of every input. Each message of the
  trigger input builds a bundle, one keyword per input, for one call of
  ``process``; any other message only replaces the newest of its input.

**Age is message time, not wall-clock time.** An input is stale when the
trigger's ``timestamp`` is more than its ``max_age`` seconds after the input's
own, so a replay behaves exactly as the live feed it recorded. A message
without a ``timestamp`` (on either side) cannot be judged and counts as fresh;
an input newer than the trigger is fresh too.

What a stale or never-seen input does is ``missing``: ``"skip"`` drops the
call (``feed`` returns ``None``), ``"none"`` passes ``None`` for that input.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeVar

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

__all__ = ["Latest", "handlers_of", "on"]

F = TypeVar("F", bound=Callable[..., Any])

#: The attribute ``on`` sets on a handler: the message class it handles.
_MARK = "__pswamp_on__"


def on(model: type[DataModel]) -> Callable[[F], F]:
    """Mark a method as the handler of one input class. The module lists that
    class in ``inputs``; every input then has exactly one handler."""

    def mark(handler: F) -> F:
        setattr(handler, _MARK, model)
        return handler

    return mark


def handlers_of(cls: type) -> dict[type[DataModel], str]:
    """The ``@on`` handlers of ``cls`` and its bases, as input class → method
    name. A subclass overriding a handler by name keeps its mark only if it
    marks it again. Two handlers for one class raise ``TypeError``."""
    found: dict[type[DataModel], str] = {}
    seen: set[str] = set()
    for klass in cls.__mro__:
        for name, attribute in vars(klass).items():
            if name in seen:
                continue
            seen.add(name)
            model = getattr(attribute, _MARK, None)
            if model is None:
                continue
            if model in found:
                raise TypeError(f"{cls.__name__}: {found[model]} and {name} both handle {model.__name__}")
            found[model] = name
    return found


@dataclass
class Latest:
    """The trigger input's message plus the newest of every other input.

    Declared on a module class as configuration; each module instance works
    on a fresh copy bound to its inputs (``bound``), which then holds state.

    Args:
        trigger: The input name whose every message makes one call.
        max_age: Seconds, per non-trigger input: how much older than the
            trigger it may be. An input not listed never goes stale.
        missing: ``"skip"`` drops a call that lacks an input (never seen, or
            stale); ``"none"`` makes it with ``None`` for that input.
    """

    trigger: str
    max_age: Mapping[str, float] = field(default_factory=dict)
    missing: Literal["skip", "none"] = "skip"
    _inputs: dict[str, type[DataModel]] = field(default_factory=dict, init=False, repr=False)
    _by_class: dict[type[DataModel], str] = field(default_factory=dict, init=False, repr=False)
    _newest: dict[str, DataModel] = field(default_factory=dict, init=False, repr=False)

    def check(self, inputs: Mapping[str, type[DataModel]], owner: str = "the module") -> None:
        """Raise ``TypeError`` if this join does not fit ``inputs``."""
        if self.missing not in ("skip", "none"):
            raise TypeError(f"{owner}: Latest(missing={self.missing!r}) must be 'skip' or 'none'")
        if self.trigger not in inputs:
            raise TypeError(f"{owner}: the join's trigger {self.trigger!r} is not one of its inputs {sorted(inputs)}")
        unknown = sorted(set(self.max_age) - set(inputs))
        if unknown:
            raise TypeError(f"{owner}: max_age names {unknown}, which are not among its inputs {sorted(inputs)}")
        if self.trigger in self.max_age:
            raise TypeError(f"{owner}: max_age cannot apply to the trigger {self.trigger!r}")
        classes = list(inputs.values())
        if len(set(classes)) != len(classes):
            raise TypeError(f"{owner}: two inputs have the same class; a topic carries one class, so name it once")

    def bound(self, inputs: Mapping[str, type[DataModel]]) -> Latest:
        """A fresh, empty join over ``inputs``: what a module instance uses."""
        self.check(inputs)
        join = Latest(self.trigger, dict(self.max_age), self.missing)
        join._inputs = dict(inputs)
        join._by_class = {model: name for name, model in inputs.items()}
        return join

    @property
    def trigger_model(self) -> type[DataModel]:
        """The trigger input's class (on a bound join)."""
        return self._inputs[self.trigger]

    def name_of(self, message: DataModel) -> str:
        """The input name ``message`` arrives as; ``TypeError`` if none."""
        name = self._by_class.get(type(message))
        if name is None:
            raise TypeError(f"{type(message).__name__} is not one of the inputs {sorted(self._inputs)}")
        return name

    def feed(self, message: DataModel) -> dict[str, DataModel | None] | None:
        """Take one message. A trigger returns the bundle for one call, or
        ``None`` when ``missing="skip"`` and an input is missing or stale; any
        other input returns ``None`` after replacing that input's newest."""
        name = self.name_of(message)
        if name != self.trigger:
            self._newest[name] = message
            return None
        bundle: dict[str, DataModel | None] = {}
        for other in self._inputs:
            if other == self.trigger:
                bundle[other] = message
                continue
            value = self._newest.get(other)
            if value is None or self._stale(other, value, message):
                if self.missing == "skip":
                    return None
                value = None
            bundle[other] = value
        return bundle

    def _stale(self, name: str, value: DataModel, trigger: DataModel) -> bool:
        limit = self.max_age.get(name)
        if limit is None or value.timestamp is None or trigger.timestamp is None:
            return False
        return (trigger.timestamp - value.timestamp).total_seconds() > limit
