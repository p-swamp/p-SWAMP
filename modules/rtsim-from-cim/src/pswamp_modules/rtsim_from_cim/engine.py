# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SimEngine``: the TOPS system the engine's process steps, fed what to do by ``LiveTops``.

Pure and synchronous: no clock, no thread, no event loop::

    sim = get_exporter("tops", repo, **EXPORT).build()
    engine = SimEngine(sim.model, dt=0.01)
    engine.apply(("event", ("switches", "Switch", name, "open", {})))   # what LiveTops sent
    snapshot = engine.step(steps=4)                                       # advance 4 steps and sample

It knows nothing of the CIM graph. ``LiveTops`` (LazyCIM), in the controller (``follow``), decides
what the graph's changes and the commands mean for TOPS, and sends each as a message (``runner``):
an event of a model (a switch opened, a line disconnected, a load's power set), or an input set on
a model (a controller's bias). This applies it, as TOPS 0.6 does, keeping the transient. A model
that changed more than a running simulation can absorb is sent whole, and the engine starts over
from it at steady state, the clock running on (``rebuild``).

``step`` raises ``ArithmeticError`` when the run diverges (a state that is not finite, or a bus
voltage past ``MAX_V_PU``); the engine is then to be thrown away.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import numpy as np
import tops.dynamic as dynamic
from tops.simulator import Simulator

__all__ = ["DEFAULT_DYNAMICS", "EXPORT", "MAX_V_PU", "SimEngine", "Snapshot"]

#: Past this a bus voltage is not physical any more: the run has diverged.
MAX_V_PU = 5.0

#: A machine's per-unit parameters when the graph holds none for it (the TOPS model's names:
#: ``X_d_t`` is X'd, ``X_d_st`` is X''d). What the graph holds wins.
DEFAULT_DYNAMICS = {
    "H": 5.0, "D": 0.0, "X_d": 2.2, "X_q": 2.1, "X_d_t": 0.3, "X_q_t": 0.5, "X_d_st": 0.2, "X_q_st": 0.2,
    "T_d0_t": 5.0, "T_q0_t": 1.0, "T_d0_st": 0.05, "T_q0_st": 0.05,
}  # fmt: skip

#: How the graph is exported (LazyCIM's TOPS exporter): every node a bus and every switch a TOPS
#: ``Switch`` (its default topology), the parts the slack bus cannot reach left out, and a PLL on
#: every bus to measure the frequency.
EXPORT = {"defaults": DEFAULT_DYNAMICS, "plls": True}


@dataclass(frozen=True)
class Snapshot:
    """The simulation at one instant: arrays are copies, in the model's bus and line order."""

    sim_time_s: float
    v_pu: np.ndarray
    angle_deg: np.ndarray
    f_hz: np.ndarray
    #: Each line's current at its first and second end, complex, kA.
    i_from_ka: np.ndarray
    i_to_ka: np.ndarray


class SimEngine:
    """A TOPS system built from ``model`` (``sim.model``); ``dt`` is the integration step in simulated
    seconds."""

    def __init__(self, model: dict[str, Any], *, dt: float = 0.01) -> None:
        self.dt = dt
        #: Simulated seconds before the current build: the clock runs on across ``rebuild``.
        self._time = 0.0
        #: How many times the model was built: a caller that derives from it knows to derive again.
        self.builds = 0
        self._build(model)

    def _build(self, model: dict[str, Any]) -> None:
        with np.errstate(all="ignore"):
            ps = dynamic.PowerSystemModel(model=copy.deepcopy(model))
            ps.init_dyn_sim()
            sim = Simulator(ps, dt=self.dt)
        self._ps, self._sim = ps, sim
        self._line, self._pll = ps.lines["Line"], ps.pll["PLL1"]
        self.bus_names = [str(name) for name in ps.buses["name"]]
        self.bus_kv = np.asarray(ps.buses["V_n"], dtype=float)
        self.line_names = [str(name) for name in self._line.par["name"]]
        self.builds += 1

    def rebuild(self, model: dict[str, Any]) -> None:
        """Start over from ``model`` at steady state; the clock runs on. Raises what TOPS raises, and
        then the running simulation goes on as it was."""
        time = self._time + float(self._sim.sol.t)
        self._build(model)
        self._time = time

    # -- what the controller sends ------------------------------------------------------------

    def apply(self, message: tuple) -> None:
        """Do what ``message`` says: ``("event", (category, model, unit, action, kwargs))``, a TOPS
        event; or ``("input", (category, model, input, value, index))``, an input set on a model.
        Raises what TOPS raises for one that does not apply (``KeyError``, ``ValueError``)."""
        kind, what = message
        with np.errstate(all="ignore"):
            if kind == "event":
                category, model, unit, action, kwargs = what
                self._ps.apply_event(category, model, unit, action, **kwargs)
            elif kind == "input":
                category, model, name, value, index = what
                self._ps.dyn_mdls_dict[category][model].set_input(name, value, index)
            else:
                raise ValueError(f"no idea what to do with {kind!r}")

    # -- stepping ----------------------------------------------------------------------------

    def step(self, steps: int = 1) -> Snapshot:
        """Advance ``steps`` steps and sample."""
        with np.errstate(all="ignore"):
            for _ in range(steps):
                self._sim.make_simulation_step()
            if not (np.isfinite(self._sim.sol.y).all() and np.isfinite(self._sim.sol.v).all()):
                raise ArithmeticError("the state is not finite")
            snapshot = self.snapshot()
        highest = float(np.nanmax(snapshot.v_pu))
        if highest > MAX_V_PU:
            raise ArithmeticError(f"a bus voltage reached {highest:.1f} p.u.")
        return snapshot

    def state(self) -> tuple[float, np.ndarray, np.ndarray]:
        """The build's time, its states and its bus voltages, copied: what a shadow of the system (the
        controller's ``LiveTops``) reads from."""
        sol = self._sim.sol
        return float(sol.t), np.array(sol.y, copy=True), np.array(sol.v, copy=True)

    def snapshot(self) -> Snapshot:
        """The simulation as it is, copied. Cheap enough to call once per frame."""
        sol = self._sim.sol
        t, y, v = float(sol.t), sol.y, sol.v
        with np.errstate(all="ignore"):
            f_hz = self._ps.f_n * (1.0 + self._pll.freq_est(y, v))
            i_from, i_to = self._line.I_from(y, v), self._line.I_to(y, v)
        return Snapshot(
            self._time + t,
            np.abs(v).astype(float),
            np.degrees(np.angle(v)).astype(float),
            np.asarray(f_hz, dtype=float),
            np.asarray(i_from, dtype=complex),
            np.asarray(i_to, dtype=complex),
        )
