# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SimEngine``: a TOPS simulation of a model LazyCIM exported, stepped by whoever owns the clock.

Pure and synchronous: no clock, no thread, no event loop::

    sim = get_exporter("tops", repo, **EXPORT).build()
    engine = SimEngine(sim.model, open_switches=sim.ids["open_switches"])
    engine.apply(change)              # follow the graph: a switch, a load, or a new model
    snapshot = engine.step(steps=4)   # advance 4 steps and sample

The model is LazyCIM's TOPS export (``EXPORT``): every switch is a branch of its own, so the buses
never change and a switch the graph opens or closes is a ``Line.event`` on its row, which keeps the
transient it causes; a PLL on every bus measures the frequency; the machines' governors, exciters
and stabilisers come from the graph. Each bus also gets a negligible shunt to ground, so a node that
switches leave floating (both ends of a bay open) reads 0 V rather than making the network singular.

A line or a transformer whose terminal is disconnected (its row leaves the export) is taken out the
same way, live: a ``Line.event`` for a line, and for a transformer, which TOPS has no event for, its
admittance taken off the network (``_transformer``). A ``Change`` that a running simulation cannot
absorb (other rows came or went: a machine added) carries a whole new model, and the engine starts
over from it at steady state.
``step`` raises ``ArithmeticError`` when the run diverges (a state that is not finite, or a bus
voltage past ``MAX_V_PU``); the engine is then to be thrown away.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import tops.dynamic as dynamic
import tops.solvers as solvers
from lazycim.sim import RowChange
from pswamp_core.log import get_logger
from scipy.sparse import lil_matrix

__all__ = ["DEFAULT_DYNAMICS", "EXPORT", "NOMINAL_HZ", "Change", "SimEngine", "Snapshot"]

logger = get_logger("pswamp_modules.rtsim_from_cim")

#: Past this a bus voltage is not physical any more: the run has diverged.
MAX_V_PU = 5.0
NOMINAL_HZ = 50.0
#: Mvar of the shunt to ground on every bus: nothing to the grid, enough to keep a floating node solvable.
GROUNDING_MVAR = 1e-3

#: A machine's per-unit parameters when the graph holds none for it (the TOPS model's names:
#: ``X_d_t`` is X'd, ``X_d_st`` is X''d). What the graph holds wins.
DEFAULT_DYNAMICS = {
    "H": 5.0, "D": 0.0, "X_d": 2.2, "X_q": 2.1, "X_d_t": 0.3, "X_q_t": 0.5, "X_d_st": 0.2, "X_q_st": 0.2,
    "T_d0_t": 5.0, "T_q0_t": 1.0, "T_d0_st": 0.05, "T_q0_st": 0.05,
}  # fmt: skip

#: How the graph is exported: see the module.
EXPORT = {"defaults": DEFAULT_DYNAMICS, "plls": True, "switches_as_branches": True, "open_switches": "post_init"}


@dataclass(frozen=True)
class Change:
    """What the graph changed, as the engine applies it."""

    #: Switch branches and lines (row names) to open, and to close.
    opened: frozenset[str] = frozenset()
    closed: frozenset[str] = frozenset()
    #: Transformers (row names) to take out, and to bring back (a terminal disconnected, or connected
    #: again: the export drops their row, then brings it back).
    transformers_out: frozenset[str] = frozenset()
    transformers_in: frozenset[str] = frozenset()
    #: Values that moved in rows the model has (LazyCIM's ``RowChange``).
    values: tuple[RowChange, ...] = ()
    #: A whole new model, its rows' mRIDs (``sim.ids``) and its open switches, when the change cannot
    #: be absorbed live.
    model: dict[str, Any] | None = None
    ids: dict[str, Any] | None = None
    open_switches: frozenset[str] = field(default_factory=frozenset)
    reason: str | None = None
    #: The model comes only in case the events cannot be applied (a branch coming back to a part of
    #: the grid the running model left out): then it is built again.
    live: bool = False

    def __bool__(self) -> bool:
        return bool(
            self.opened or self.closed or self.transformers_out or self.transformers_in or self.values or self.model is not None
        )


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
    """A TOPS system built from ``model`` (``sim.model``), with the switches ``open_switches`` (row
    names, ``sim.ids["open_switches"]``) open; ``dt`` is the integration step in simulated seconds."""

    def __init__(self, model: dict[str, Any], *, open_switches=(), dt: float = 0.01) -> None:
        self.dt = dt
        self._build(model, frozenset(open_switches))

    def _build(self, model: dict[str, Any], open_switches: frozenset[str]) -> None:
        model = copy.deepcopy(model)
        # LazyCIM 0.2.1 read a breaker as a Switch too, so each switch was exported twice under
        # one name: two branches in parallel, of which an event would open only one (not 0.2.2).
        header, *rows = model["lines"]
        model["lines"] = [header, *{row[0]: row for row in rows}.values()]
        dead = _energise(model)
        if dead:
            logger.info("%d buses the slack bus cannot reach are left out, de-energised: %s", len(dead), ", ".join(sorted(dead)))
        buses = model["buses"][1:]
        model["shunts"] = [*model["shunts"], *([f"ground {name}", name, kv, GROUNDING_MVAR, "Z"] for name, kv in buses)]
        with np.errstate(all="ignore"):
            ps = dynamic.PowerSystemModel(model=model)
            ps.init_dyn_sim()
        if not getattr(ps, "power_flow_ready", False):
            raise RuntimeError("the load flow did not converge")
        self._ps, self._line, self._pll = ps, ps.lines["Line"], ps.pll["PLL1"]
        self._trafo = getattr(ps, "trafos", {}).get("Trafo")
        self.bus_names = [name for name, _ in buses]
        self.bus_kv = np.array([float(kv) for _, kv in buses])
        self.line_names = list(self._line.par["name"])
        self.transformer_names = list(self._trafo.par["name"]) if self._trafo is not None else []
        self._open: set[str] = set()
        self._out: set[str] = set()  # the transformers taken out
        for name in sorted(open_switches):
            self._event(name, "disconnect")
        with np.errstate(all="ignore"):
            self._solver = solvers.ModifiedEulerDAE(
                ps.state_derivatives, ps.solve_algebraic, 0, ps.x0, max_step=self.dt, first_step=self.dt
            )
        self._time = getattr(self, "_time", 0.0)
        #: How many times the model was built: a caller that derives from it knows to derive again.
        self.builds = getattr(self, "builds", 0) + 1


    # -- following the graph ---------------------------------------------------------------

    def apply(self, change: Change) -> list[str]:
        """Follow the graph; return what was done, one line of text each."""
        if change.live and (change.closed - set(self.line_names) or change.transformers_in - set(self.transformer_names)):
            change = Change(model=change.model, ids=change.ids, open_switches=change.open_switches, reason=change.reason)
        if change.model is not None and not change.live:
            time = self._time + self._solver.t
            try:
                self._build(change.model, change.open_switches)
            except Exception as error:  # whatever the new model is, the running one is not given up for it
                return [f"the model could not be built again ({change.reason}): {error}; the simulation goes on as it was"]
            self._time = time
            return [f"the model was built again ({change.reason}): the simulation starts over at steady state"]
        done = [self._event(name, "disconnect") for name in sorted(change.opened)]
        done += [self._event(name, "connect") for name in sorted(change.closed)]
        done += [self._transformer(name, connect=False) for name in sorted(change.transformers_out)]
        done += [self._transformer(name, connect=True) for name in sorted(change.transformers_in)]
        done += [self._value(value) for value in change.values]
        return [line for line in done if line]

    def _event(self, name: str, event: str) -> str:
        if name not in self.line_names:
            return f"{name} is not in the model: it cannot be {event}ed"
        if (name in self._open) == (event == "disconnect"):
            return ""
        with np.errstate(all="ignore"):
            self._line.event(self._ps, name, event)
        (self._open.add if event == "disconnect" else self._open.discard)(name)
        return f"{name} {event}ed"

    def _transformer(self, name: str, *, connect: bool) -> str:
        """A transformer taken out or brought back: what ``Line.event`` does for a line, which TOPS has
        no counterpart of for a transformer. Its admittance, as TOPS stamped it into the network (with
        its ratios), comes off the network or goes back on, and its currents read 0 while it is out."""
        event = "connect" if connect else "disconnect"
        if name not in self.transformer_names:
            return f"transformer {name} is not in the model: it cannot be {event}ed"
        if (name in self._out) != connect:
            return ""
        trafo, i = self._trafo, self.transformer_names.index(name)
        f, t = trafo.bus_idx_red["from_bus"][i], trafo.bus_idx_red["to_bus"][i]
        if f < 0 or t < 0:  # TOPS's mark for a bus outside the reduced network
            return f"transformer {name}: its buses are not in the network, it cannot be {event}ed"
        y, r_from, r_to = trafo.admittance[i], trafo.ratio_from_0[i], trafo.ratio_to_0[i]
        delta = lil_matrix(self._ps.y_bus_red.shape, dtype=complex)
        delta[f, f] += r_from * np.conj(r_from) * y
        delta[t, t] += r_to * np.conj(r_to) * y
        delta[f, t] += -r_from * np.conj(r_to) * y
        delta[t, f] += -np.conj(r_from) * r_to * y
        self._ps.y_bus_red = self._ps.y_bus_red + (delta if connect else -delta)
        trafo.connected[i] = connect
        (self._out.discard if connect else self._out.add)(name)
        return f"transformer {name} {event}ed"

    def _value(self, change: RowChange) -> str:
        if change.component == "loads" and change.column in ("P", "Q"):
            return self._load(change.name, **{change.column: float(change.new)})
        return f"{change.component} {change.name}: {change.column} {change.old} -> {change.new} is not followed live"

    def _load(self, name: str, **power: float) -> str:
        """A load drawing other power: its admittance, as TOPS sets it at the initial voltage, moves."""
        load = self._ps.loads["Load"]
        rows = list(load.par["name"])
        if name not in rows:
            return f"load {name} is not in the model"
        i = rows.index(name)
        for column, value in power.items():
            load.par[column][i] = value
        s = (load.par["P"][i] + 1j * load.par["Q"][i]) / load.sys_par["s_n"]
        admittance = np.conj(s) / abs(load.v_0[i]) ** 2
        delta = lil_matrix(self._ps.y_bus_red.shape, dtype=complex)
        bus = load.bus_idx_red["terminal"][i]
        delta[bus, bus] = admittance - load.y_load[i]
        load.y_load[i] = admittance
        self._ps.y_bus_red = self._ps.y_bus_red + delta
        return f"load {name}: {', '.join(f'{k} {v:g}' for k, v in power.items())}"

    # -- stepping ----------------------------------------------------------------------------

    def step(self, steps: int = 1) -> Snapshot:
        """Advance ``steps`` steps and sample."""
        with np.errstate(all="ignore"):
            for _ in range(steps):
                self._solver.step()
            if not np.isfinite(self._solver.y).all():
                raise ArithmeticError("the state is not finite")
            snapshot = self.snapshot()
        highest = float(np.nanmax(snapshot.v_pu))
        if highest > MAX_V_PU:
            raise ArithmeticError(f"a bus voltage reached {highest:.1f} p.u.")
        return snapshot

    def snapshot(self) -> Snapshot:
        """The simulation as it is, copied. Cheap enough to call once per frame."""
        t, y = float(self._solver.t), self._solver.y
        with np.errstate(all="ignore"):
            v = self._ps.solve_algebraic(t, y)
            f_hz = NOMINAL_HZ * (1.0 + self._pll.freq_est(y, v))
            i_from, i_to = self._line.I_from(y, v), self._line.I_to(y, v)
        return Snapshot(
            self._time + t,
            np.abs(v).astype(float),
            np.degrees(np.angle(v)).astype(float),
            np.asarray(f_hz, dtype=float),
            np.asarray(i_from, dtype=complex),
            np.asarray(i_to, dtype=complex),
        )


def _energise(model: dict[str, Any]) -> set[str]:
    """Leave out of ``model``, in place, the buses the slack bus cannot reach through its lines and
    transformers, and everything on them; return them. TOPS solves one connected grid: an island (a
    substation whose only line is out) makes its load flow singular. What is left out is de-energised."""
    links: dict[str, set[str]] = {}
    for component in ("lines", "transformers"):
        for row in model[component][1:]:
            links.setdefault(row[1], set()).add(row[2])
            links.setdefault(row[2], set()).add(row[1])
    reach, todo = {model["slack_bus"]}, [model["slack_bus"]]
    while todo:
        for other in links.get(todo.pop(), ()):
            if other not in reach:
                reach.add(other)
                todo.append(other)
    dead = {row[0] for row in model["buses"][1:]} - reach
    if not dead:
        return dead

    def keep(rows: list, column: int, gone: set[str]) -> list:
        return [rows[0], *(row for row in rows[1:] if row[column] not in gone)]

    model["buses"] = keep(model["buses"], 0, dead)
    for component in ("lines", "transformers"):
        model[component] = keep(keep(model[component], 1, dead), 2, dead)
    for component in ("loads", "shunts"):
        model[component] = keep(model[component], 1, dead)
    generators = model["generators"]["GEN"]
    gone = {row[0] for row in generators[1:] if row[1] in dead}
    model["generators"]["GEN"] = keep(generators, 1, dead)
    if "pll" in model:
        model["pll"]["PLL1"] = keep(model["pll"]["PLL1"], 2, dead)
    for group in ("gov", "avr", "pss"):
        tables = {name: keep(rows, 1, gone) for name, rows in model.get(group, {}).items()}
        tables = {name: rows for name, rows in tables.items() if len(rows) > 1}
        if tables:
            model[group] = tables
        else:
            model.pop(group, None)
    return dead
