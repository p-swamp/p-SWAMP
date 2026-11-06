# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SimEngine``: the TOPS system the engine's process steps, fed what to do by ``LiveTops``.

Pure and synchronous: no clock, no thread, no event loop::

    live = LiveTops.from_repo(repo, **EXPORT)
    engine = SimEngine(live.built.model, dt=0.01, events=live.built.events)
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

__all__ = ["DEFAULT_DYNAMICS", "EXPORT", "MAX_V_PU", "Flows", "SimEngine", "Snapshot"]

#: Past this a bus voltage is not physical any more: the run has diverged.
MAX_V_PU = 5.0

#: A machine's per-unit parameters when the graph holds none for it (the TOPS model's names:
#: ``X_d_t`` is X'd, ``X_d_st`` is X''d). What the graph holds wins.
DEFAULT_DYNAMICS = {
    "H": 5.0, "D": 0.0, "X_d": 2.2, "X_q": 2.1, "X_d_t": 0.3, "X_q_t": 0.5, "X_d_st": 0.2, "X_q_st": 0.2,
    "T_d0_t": 5.0, "T_q0_t": 1.0, "T_d0_st": 0.05, "T_q0_st": 0.05,
}  # fmt: skip

#: How the graph is exported (LazyCIM's TOPS exporter): every node a bus and every switch a TOPS
#: ``Switch`` (its default topology), the parts the slack bus cannot reach kept (``LiveTops``'s
#: default: an island formed while running runs on), and a PLL on every bus to measure the frequency.
EXPORT = {"defaults": DEFAULT_DYNAMICS, "plls": True}


@dataclass(frozen=True)
class Snapshot:
    """The simulation at one instant: arrays are copies, in the model's bus and line order."""

    sim_time_s: float
    v_pu: np.ndarray
    angle_deg: np.ndarray
    f_hz: np.ndarray
    #: Each bus's rate of change of frequency over the last steps, Hz/s (zero for a snapshot not stepped to).
    rocof_hz_s: np.ndarray
    #: Each line's current at its from and to end, complex, kA.
    i_from_ka: np.ndarray
    i_to_ka: np.ndarray
    #: Each transformer's current at its from and to end, complex, kA, in ``trafo_names`` order.
    t_from_ka: np.ndarray
    t_to_ka: np.ndarray
    #: Each machine's electrical power, MW and Mvar, in ``gen_names`` order.
    gen_p_mw: np.ndarray
    gen_q_mvar: np.ndarray
    #: Each load's power, MW and Mvar, in ``load_names`` order.
    load_p_mw: np.ndarray
    load_q_mvar: np.ndarray


@dataclass(frozen=True)
class Flows:
    """What a SCADA scan reads, at one instant: arrays are copies, in the model's orders. A branch's
    ``from`` end is its first bus in the model, its ``to`` end the second; its power at an end flows into
    it there."""

    sim_time_s: float
    v_pu: np.ndarray
    #: Each line's, then each transformer's, power at its from and to end, complex, MVA.
    s_from_mva: np.ndarray
    s_to_mva: np.ndarray
    #: Each line's, then each transformer's, current at its from and to end, complex, kA.
    i_from_ka: np.ndarray
    i_to_ka: np.ndarray
    #: Each machine's power (as it generates), then each load's (as it draws), MW and Mvar.
    p_mw: np.ndarray
    q_mvar: np.ndarray
    #: Whether each switch is closed, in ``switch_names`` order.
    closed: np.ndarray


class SimEngine:
    """A TOPS system built from ``model`` (``LiveTops.built.model``), with ``events`` applied right after
    its initialisation (``LiveTops.built.events``: the branches that join a part built at once and cut
    off again); ``dt`` is the integration step in simulated seconds."""

    def __init__(self, model: dict[str, Any], *, dt: float = 0.01, events: list[tuple] = ()) -> None:
        self.dt = dt
        #: Simulated seconds before the current build: the clock runs on across ``rebuild``.
        self._time = 0.0
        #: How many times the model was built: a caller that derives from it knows to derive again.
        self.builds = 0
        #: Messages for later, ``(time on the build's clock, messages)``: a fault's clearing, say.
        self._later: list[tuple[float, list[tuple]]] = []
        self._build(model, events)

    def _build(self, model: dict[str, Any], events: list[tuple] = ()) -> None:
        with np.errstate(all="ignore"):
            ps = dynamic.PowerSystemModel(model=copy.deepcopy(model))
            ps.init_dyn_sim()
            for event in events:
                ps.apply_event(*event)
            sim = Simulator(ps, dt=self.dt)
        self._ps, self._sim = ps, sim
        self._line, self._pll = ps.lines["Line"], ps.pll["PLL1"]
        self._trafo = getattr(ps, "trafos", {}).get("Trafo")
        self._switch = ps.dyn_mdls_dict.get("switches", {}).get("Switch")
        self.bus_names = [str(name) for name in ps.buses["name"]]
        self.bus_kv = np.asarray(ps.buses["V_n"], dtype=float)
        self.line_names = [str(name) for name in self._line.par["name"]]
        #: Each line's and transformer's (from bus, to bus), by name.
        self.line_buses = [(str(a), str(b)) for a, b in zip(self._line.par["from_bus"], self._line.par["to_bus"], strict=True)]
        trafo = self._trafo.par if self._trafo is not None else {"name": [], "from_bus": [], "to_bus": []}
        self.trafo_names = [str(name) for name in trafo["name"]]
        self.trafo_buses = [(str(a), str(b)) for a, b in zip(trafo["from_bus"], trafo["to_bus"], strict=True)]
        self.switch_names = [str(name) for name in self._switch.par["name"]] if self._switch is not None else []
        self._gens = list(ps.gen.values())
        self._loads = list(ps.loads.values())  # every load model of the model: Load, and any other
        self.gen_names = [str(name) for model in self._gens for name in model.par["name"]]
        self.load_names = [str(name) for model in self._loads for name in model.par["name"]]
        self.builds += 1

    def rebuild(self, model: dict[str, Any], events: list[tuple] = ()) -> None:
        """Start over from ``model`` at steady state, ``events`` applied; the clock runs on. Raises what
        TOPS raises, and then the running simulation goes on as it was."""
        time = self._time + float(self._sim.sol.t)
        self._build(model, events)
        self._time = time
        self._later = []  # what was for later was for the system that is gone

    # -- what the controller sends ------------------------------------------------------------

    def apply(self, message: tuple) -> None:
        """Do what ``message`` says: ``("event", (category, model, unit, action, kwargs))``, a TOPS
        event; ``("input", (category, model, input, value, index))``, an input set on a model; or
        ``("at", t, messages)``, messages to apply once the build's clock reaches ``t`` (``due``).
        Raises what TOPS raises for one that does not apply (``KeyError``, ``ValueError``)."""
        if message[0] == "at":
            _, t, messages = message
            self._later.append((float(t), list(messages)))
            return
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

    def due(self) -> list[tuple]:
        """The messages for later whose time has come, in the order they were sent: once each."""
        now = float(self._sim.sol.t) + 1e-9
        ready = [messages for t, messages in self._later if t <= now]
        self._later = [(t, messages) for t, messages in self._later if t > now]
        return [message for messages in ready for message in messages]

    # -- stepping ----------------------------------------------------------------------------

    def step(self, steps: int = 1) -> Snapshot:
        """Advance ``steps`` steps and sample."""
        with np.errstate(all="ignore"):
            before = self._f_hz(self._sim.sol.y, self._sim.sol.v)
            for _ in range(steps):
                self._sim.make_simulation_step()
            if not (np.isfinite(self._sim.sol.y).all() and np.isfinite(self._sim.sol.v).all()):
                raise ArithmeticError("the state is not finite")
            snapshot = self.snapshot(since=(before, steps * self.dt))
        highest = float(np.nanmax(snapshot.v_pu))
        if highest > MAX_V_PU:
            raise ArithmeticError(f"a bus voltage reached {highest:.1f} p.u.")
        return snapshot

    def state(self) -> tuple[float, np.ndarray, np.ndarray]:
        """The build's time, its states and its bus voltages, copied: what a shadow of the system (the
        controller's ``LiveTops``) reads from."""
        sol = self._sim.sol
        return float(sol.t), np.array(sol.y, copy=True), np.array(sol.v, copy=True)

    def _f_hz(self, y: np.ndarray, v: np.ndarray) -> np.ndarray:
        return np.asarray(self._ps.f_n * (1.0 + self._pll.freq_est(y, v)), dtype=float)

    def snapshot(self, since: tuple[np.ndarray, float] | None = None) -> Snapshot:
        """The simulation as it is, copied. Cheap enough to call once per frame. ``since``, the
        frequencies some seconds ago and how many, gives the rate of change of frequency."""
        sol = self._sim.sol
        t, y, v = float(sol.t), sol.y, sol.v
        with np.errstate(all="ignore"):
            f_hz = self._f_hz(y, v)
            rocof = (f_hz - since[0]) / since[1] if since is not None and since[1] > 0 else np.zeros_like(f_hz)
            i_from, i_to = self._line.I_from(y, v), self._line.I_to(y, v)
            if self._trafo is not None:
                t_from, t_to = self._trafo.I_from(y, v), self._trafo.I_to(y, v)
            else:
                t_from = t_to = np.zeros(0, dtype=complex)
            gen_p, gen_q = _each(self._gens, "P_e", y, v), _each(self._gens, "Q_e", y, v)
            load_p, load_q = _each(self._loads, "P", y, v), _each(self._loads, "Q", y, v)
        return Snapshot(
            self._time + t,
            np.abs(v).astype(float),
            np.degrees(np.angle(v)).astype(float),
            f_hz,
            np.asarray(rocof, dtype=float),
            np.asarray(i_from, dtype=complex),
            np.asarray(i_to, dtype=complex),
            np.asarray(t_from, dtype=complex),
            np.asarray(t_to, dtype=complex),
            gen_p,
            gen_q,
            load_p,
            load_q,
        )

    def flows(self) -> Flows:
        """What a SCADA scan reads (``Flows``), as the simulation is now: once a scan, not per frame."""
        sol = self._sim.sol
        t, y, v = float(sol.t), sol.y, sol.v
        s_n = float(self._ps.s_n)
        branches = [self._line] + ([self._trafo] if self._trafo is not None else [])
        with np.errstate(all="ignore"):
            joined = lambda f: np.concatenate([np.asarray(f(b), dtype=complex).ravel() for b in branches])  # noqa: E731
            return Flows(
                self._time + t,
                np.abs(v).astype(float),
                joined(lambda b: b.s_from(y, v)) * s_n,
                joined(lambda b: b.s_to(y, v)) * s_n,
                joined(lambda b: b.I_from(y, v)),
                joined(lambda b: b.I_to(y, v)),
                np.concatenate([_each(self._gens, "P_e", y, v), _each(self._loads, "P", y, v)]),
                np.concatenate([_each(self._gens, "Q_e", y, v), _each(self._loads, "Q", y, v)]),
                np.array(self._switch.connected, dtype=bool, copy=True) if self._switch is not None else np.zeros(0, dtype=bool),
            )


def _each(models: list, output: str, y: np.ndarray, v: np.ndarray) -> np.ndarray:
    """``output`` of every unit of ``models`` (TOPS models of one kind: ``P_e`` of each GEN, MW), one
    array in their order."""
    if not models:
        return np.zeros(0)
    return np.concatenate([np.asarray(getattr(model, output)(y, v), dtype=float).ravel() for model in models])
