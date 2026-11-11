# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``RemoteRunner``: LazyCIM's ``LiveTops`` steering a TOPS simulation that runs in another process.

``LiveTops`` holds the repository and decides what the graph's changes and the commands mean for
TOPS; the simulation steps in the engine's process (``process``), because the stepping must never
wait for the interpreter behind a refresh. This stands in for TOPS's simulator inside ``LiveTops``:

- what ``LiveTops`` applies goes to its **shadow**, the TOPS system it built and never steps, and
  down to the engine as a message (``("event", ...)``, ``("input", ...)``), in the order applied;
- the state the engine sends back each frame (``receive``) is what ``LiveTops`` reads from: its time,
  its voltages and currents, and which commands the engine applied or rejected;
- a model that has to be built again is built by ``LiveTops`` and sent whole (``("build", ...)``), as
  ``LiveTops.built`` has it: the model, less the parts left out, and the events applied right after.

**What this relies on in LazyCIM that is not public** (``lazycim/sim/tops_live.py``), until
``LiveTops`` takes a runner of its own (LazyCIM, later):

- installing a stand-in for the simulator: ``_offset``, ``simulator``, ``_rows`` and ``_seen`` are
  set as ``LiveTops.realtime()`` sets them;
- a rebuild while it "runs" raises in ``follow``; ``follow`` here stops it, has ``LiveTops`` build
  again, which leaves a local simulator, and installs itself again (``_stale`` says why);
- a machine's voltage and power are set with ``set_input`` on the shadow's models, not through
  ``apply_event``: the shadow's ``set_input`` is wrapped to send them down too;
- ``LiveTops.events()`` is never used: it would replace a schedule the engine never sees;
- a restart from the graph (``restart``) marks ``LiveTops`` stale (``_stale``), as a refresh that
  cannot be absorbed does, and follows;
- a message for later (``at``) is timed on the engine's clock, which is ``LiveTops``'s less
  ``_offset``.

A command counts as done (``LiveTops.cim_changes``) once the engine has sent a frame after it was
handed over, which may be a frame or two before the engine applied it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import numpy as np

__all__ = ["RemoteRunner", "follow", "restart"]


@dataclass
class _Solution:
    """Where ``LiveTops`` reads the simulation from: the engine's last state."""

    t: float
    y: np.ndarray
    v: np.ndarray
    #: TOPS's solvers call the states both ``y`` and ``x``.
    x: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.x = self.y


class RemoteRunner:
    """A simulator for ``live`` that runs elsewhere: what is applied goes down ``send``; the engine's
    state comes back through ``receive``. Installs itself in ``live``."""

    def __init__(self, live: Any, send: Callable[[tuple], None]) -> None:
        self._send = send
        #: Which build of the model the engine is on: a state from an earlier one is not this one's.
        self.build = 0
        #: The engine's frame count, and what it could not apply: ``((category, model, unit, action,
        #: kwargs), why)``, as ``LiveTops`` reads them off TOPS's real-time simulator.
        self.frame = 0
        self.rejected: list[tuple[tuple, str]] = []
        #: ``LiveTops`` reads how far a schedule of events went; this one never has any.
        self.events = SimpleNamespace(_next=0)
        self._alive = True
        self._take(live)
        _install(live, self)

    # -- what LiveTops calls ----------------------------------------------------------------

    def submit(self, category: str, model: str, unit: str, action: str, **kwargs: Any) -> None:
        """Apply an event to the shadow, then send it: one the shadow refuses raises, and never leaves."""
        self.ps.apply_event(category, model, unit, action, **kwargs)
        self._send(("event", (category, model, unit, action, kwargs)))

    def at(self, t: float, messages: list[tuple]) -> None:
        """Have the engine apply ``messages`` once ``LiveTops``'s clock reaches ``t``: on its own
        clock, which starts over at each build (``_offset`` is where ``LiveTops``'s was then)."""
        self._send(("at", t - self._live._offset, messages))

    def is_alive(self) -> bool:
        """Whether it stands in for a running simulation: ``LiveTops`` then submits, and will not build."""
        return self._alive

    # -- what the engine sends ----------------------------------------------------------------

    def receive(self, message: tuple) -> None:
        """Take the engine's ``("state", build, frame, t, y, v, rejected)``; one of an earlier build is
        dropped."""
        _, build, frame, t, y, v, rejected = message
        if build != self.build:
            return
        self.frame, self.sol = frame, _Solution(t, y, v)
        self.rejected.extend(rejected)

    def rebuild(self, live: Any) -> None:
        """``live`` was built again: send what it built from (``live.built``: the model, and the events
        applied right after it), and stand in for its new simulator."""
        self.build += 1
        self._take(live)
        self._send(("build", self.build, live.built.model, live.sim.ids, live.built.events))
        self._alive = True
        _install(live, self)

    # ----------------------------------------------------------------------------------------

    def _take(self, live: Any) -> None:
        """Shadow ``live``'s system, as it starts: at its power flow, at time 0."""
        self._live, self.ps = live, live.ps
        self.sol = _Solution(0.0, np.array(self.ps.x0, copy=True), np.array(self.ps.v0, copy=True))
        for category, models in self.ps.dyn_mdls_dict.items():
            for key, model in models.items():
                model.set_input = self._forwarding(model.set_input, category, key)

    def _forwarding(self, set_input: Callable, category: str, model: str) -> Callable:
        def forward(name: str, value: Any, idx: Any = None) -> None:
            set_input(name, value, idx)
            self._send(("input", (category, model, name, value, idx)))

        return forward


def _install(live: Any, runner: RemoteRunner) -> None:
    """Make ``runner`` the simulator of ``live``, its clock going on from where ``live``'s is."""
    live._offset, live.simulator, live._rows, live._seen = live.time, runner, [], 0


def follow(live: Any, runner: RemoteRunner) -> list[str]:
    """``live.follow()``, building the model again when the change asks for it: ``LiveTops`` builds it,
    and the runner sends it to the engine. A model that cannot be built leaves the simulation as it
    was. Returns what was done, one line each."""
    try:
        return live.follow()
    except RuntimeError:
        if live._stale is None:  # not the "it has to be built again" that a running simulation raises
            raise
    runner._alive = False
    said = live.follow()  # builds the model again, and a local simulator over it
    if live.simulator is runner:  # it could not be built: the running one goes on
        runner._alive = True
        return said
    runner.rebuild(live)
    return said


def restart(live: Any, runner: RemoteRunner, reason: str) -> list[str]:
    """Start the simulation over from the model the graph gives now, at steady state, the clock running
    on: whatever was done to it that the graph does not say (a line tripped, a fault) is gone."""
    live._stale = reason
    return follow(live, runner)
