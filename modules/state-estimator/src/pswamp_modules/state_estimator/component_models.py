"""Equipment models over PMU frames: the desktop package's ``pswamp.models``, sketched for the CIM graph.

The desktop package had ``Bus``, ``Line`` and ``Load`` (``desktop/src/pswamp/models``): each read its
equipment from the model database, found its PMU channels by station and channel name (``V``,
``I[<unit>]``), and turned a frame into phasors and what follows from them (power, per unit, a line
out, an angle across an open line). The same idea here, with the graph in place of the database and
the Analog in place of the channel name:

- **what there is** comes from the graph: every station (voltage level) and every branch (line and
  two-winding transformer), measured or not, with nominal voltages, parameters, current limits and
  whether the graph has the branch connected;
- **where it is measured** comes from the graph too: ``measurement_table`` lists every PMU Analog,
  with its terminal, node and equipment;
- **which column a value is in** comes from the frame: ``PmuHeader.analog`` names each column's
  Analog, so a model maps its Analogs to columns once per header, and a frame (or a samples x columns
  array of them) is then a few array operations.

A model is built with ``from_cim(repo, header)`` and called with a frame: a ``PmuFrame``, its
``values``, or a 2-D array of many (samples x columns), so the same call does one frame live and a
whole recording in a script.

**What is not measured is NaN, never a guess**: a station without a PMU voltage, a branch end without
a PMU current, a value a frame lacks. So is everything computed from it (a station's net injection,
when one of its branches is unknown). ``disconnected`` is True only for a branch whose measured ends
carry no current; ``unobserved`` says which branches no current tells anything about.

**Unless asked to estimate** (``estimate=True`` on any call): the pi model then fills the gaps from
what is measured. A station's voltage from a neighbour's and the current between them (repeated, so
an estimate can lead to the next); a branch end's current from the voltages at its ends, or zero for
a branch out (measured out, or open in the graph). ``provenance`` says, per value, which it is:
``MEASURED``, ``ESTIMATED`` or ``MISSING``. An estimate is only as good as the graph: a branch whose
current is not measured is taken to be in service when the graph says so (``in_service``, its
terminals' ``connected``; an open breaker in its bay is not looked at), so a trip the graph has not
heard of makes its model current wrong. Set ``in_service`` from what you know better.

Units are the stream's: voltage magnitudes are line-to-line kV, currents A, angles degrees in the
frame and radians in the phasors; a complex power is ``sqrt(3) V I*`` in MVA, flowing **into** the
branch at the end it is measured at (as CGMES and the stream sign it), so ``P_from + P_to`` is the
branch's losses. A sketch: no tap changers, phase shifters or three-winding transformers, the branch
shunt conductance ignored, a transformer's impedance referred to its end 1 with the ratio of its
ends' rated voltages.

The last cells demonstrate it on the offline simulation (as ``offline_sim.py``: no clock, no process):
a line trips; the models say which branch is out and the flows. Then measurements are taken away (a
line's currents, a station's voltage, and the transformer's currents, which the sample grid's PMUs do
not measure anyway), and the estimates are compared with the simulation's own values.

    uv run --package pswamp-rtsim-from-cim --extra examples python modules/rtsim-from-cim/examples/pmu_models.py
"""


from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # see offline_sim.py

from dataclasses import dataclass

import numpy as np
import pandas as pd
from lazycim import F, L
from lazycim.sim.topology import terminal_table

from pswamp_core.cim import current_limits, measurement_table, station_name
from pswamp_models.pmu import PmuFrame, PmuHeader

SQRT3 = np.sqrt(3.0)
BRANCHES = ("ACLineSegment", "PowerTransformer")

#: Where a value came from (``Branch.provenance``).
MEASURED, ESTIMATED, MISSING = 0, 1, 2
PROVENANCE = np.array(["measured", "estimated", "missing"])


def values_of(meas) -> np.ndarray:
    """A frame's values as floats (None -> NaN): a ``PmuFrame``, a list of values, or an array whose
    last axis is the columns (samples x columns)."""
    if isinstance(meas, PmuFrame):
        meas = meas.values
    return np.asarray(meas, dtype=float)


def _take(values: np.ndarray, columns: np.ndarray) -> np.ndarray:
    """``values`` at ``columns`` along the last axis; NaN where a column is -1 (not in the frame)."""
    taken = values[..., np.maximum(columns, 0)]
    return np.where(columns >= 0, taken, np.nan)


def _phasor(values: np.ndarray, magnitude: np.ndarray, angle: np.ndarray) -> np.ndarray:
    return _take(values, magnitude) * np.exp(1j * np.radians(_take(values, angle)))


def _at_rows(values: np.ndarray, rows: np.ndarray) -> np.ndarray:
    return np.where(rows >= 0, values[..., np.maximum(rows, 0)], np.nan)


class Columns:
    """A header's columns by Analog mRID: what every model maps its measurements through."""

    def __init__(self, header: PmuHeader) -> None:
        self.header = header
        self._at = {analog: i for i, analog in enumerate(header.analog or ()) if analog}

    def __call__(self, analogs) -> np.ndarray:
        """The column of each Analog, -1 for one the frame does not carry (or ``None``)."""
        return np.array([self._at.get(a, -1) if isinstance(a, str) else -1 for a in analogs], dtype=int)


def pmu_measurements(repo) -> pd.DataFrame:
    """The graph's PMU measurements (``measurement_table``, source PMU): read once, shared by the models."""
    table = measurement_table(repo)
    return table[table.source == "PMU"].reset_index(drop=True)


def _by(table: pd.DataFrame, keys: list[str], quantity: str) -> pd.Series:
    """The mRID of the measurement of ``quantity`` per ``keys`` (the first, where there are several)."""
    found = table[table.quantity == quantity].drop_duplicates(keys)
    return found.set_index(keys)["mRID"]


def _voltage_levels(repo) -> pd.DataFrame:
    """Every voltage level: its mRID, its station name (as the stream names it) and nominal kV."""
    levels = repo.query(L.VoltageLevels).to_dataframe(level=F.mRID, substation=F.Substation.name, kv=F.BaseVoltage.nominalVoltage)
    levels = levels[levels.substation.map(lambda s: isinstance(s, str)) & levels.kv.notna()].copy()
    levels["station"] = [station_name(s, kv) for s, kv in zip(levels.substation, levels.kv, strict=True)]
    return levels.drop_duplicates("station").reset_index(drop=True)


def _num(value, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) and value == value else default


# -- stations --------------------------------------------------------------------------------------


@dataclass
class Bus:
    """The stations: one per voltage level, named as the stream names them (``<substation>_<kV>``),
    whether a PMU measures it or not (its values are then NaN). The desktop ``Bus``, with the voltage
    level's mRID beside its name."""

    names: np.ndarray  # station names
    mrid: np.ndarray  # VoltageLevel mRIDs
    V_n: np.ndarray  # nominal kV
    v_columns: tuple[np.ndarray, np.ndarray]  # magnitude, angle
    f_column: np.ndarray
    df_column: np.ndarray
    v_max: float | np.ndarray = 1.1  # p.u.; the graph's VoltageLimits would be the place for these
    v_min: float | np.ndarray = 0.9

    @classmethod
    def from_cim(cls, repo, header: PmuHeader, units=None, *, measurements: pd.DataFrame | None = None) -> Bus:
        """Every station (or those of ``units``: station names or VoltageLevel mRIDs)."""
        table = pmu_measurements(repo) if measurements is None else measurements
        table = table[table.station.notna()]
        levels = _voltage_levels(repo)
        if units is not None:
            wanted = set(units)
            levels = levels[levels.station.isin(wanted) | levels.level.isin(wanted)]
        names = levels.station.to_numpy()
        at = Columns(header)
        column = lambda quantity: at(_by(table, ["station"], quantity).reindex(names))  # noqa: E731
        return cls(
            names=names,
            mrid=levels.level.to_numpy(),
            V_n=levels.kv.to_numpy(float),
            v_columns=(column("V"), column("V_angle")),
            f_column=column("F"),
            df_column=column("ROCOF"),
        )

    def index(self, names) -> np.ndarray:
        """The rows of these stations, -1 for one this model does not have."""
        row = {name: i for i, name in enumerate(self.names)}
        return np.array([row.get(name, -1) for name in names], dtype=int)

    @property
    def measured(self) -> np.ndarray:
        """Which stations a PMU measures the voltage of (in this header)."""
        return (self.v_columns[0] >= 0) & (self.v_columns[1] >= 0)

    def V(self, meas) -> np.ndarray:
        """Voltage phasor, line-to-line kV; NaN where not measured (``Branch.V`` estimates)."""
        return _phasor(values_of(meas), *self.v_columns)

    def v(self, meas) -> np.ndarray:
        """Voltage phasor, p.u. of the nominal voltage."""
        return self.V(meas) / self.V_n

    def overvoltage(self, meas) -> np.ndarray:
        return np.abs(self.v(meas)) > self.v_max

    def undervoltage(self, meas) -> np.ndarray:
        return np.abs(self.v(meas)) < self.v_min

    def freq(self, meas) -> np.ndarray:
        return _take(values_of(meas), self.f_column)

    def dfreq(self, meas) -> np.ndarray:
        """ROCOF, Hz/s."""
        return _take(values_of(meas), self.df_column)


# -- branches --------------------------------------------------------------------------------------


@dataclass
class _State:
    """One evaluation of a ``Branch`` over a frame: the stations' voltages and the ends' currents, and
    where each came from."""

    V: np.ndarray  # stations' voltages, kV (..., stations)
    I1: np.ndarray  # currents into end 1 and end 2, A (..., branches)
    I2: np.ndarray
    V_source: np.ndarray  # MEASURED / ESTIMATED / MISSING, per station
    I1_source: np.ndarray
    I2_source: np.ndarray


@dataclass
class Branch:
    """Every line and two-winding transformer of the graph: the desktop ``Line``, for both, each end's
    voltage taken from the station that end is at.

    Its pi model, in physical units referred to end 1: a series admittance ``y`` (S), a shunt
    susceptance ``b`` (S, half at each end of a line, all at end 1 of a transformer) and a ratio
    ``n`` (end 2's voltage times ``n`` is its voltage on end 1's side; 1 for a line)."""

    names: np.ndarray
    mrid: np.ndarray
    kind: np.ndarray  # ACLineSegment or PowerTransformer
    station: tuple[np.ndarray, np.ndarray]  # the station of end 1 and of end 2
    V_n: tuple[np.ndarray, np.ndarray]  # nominal kV of each end
    I_n: tuple[np.ndarray, np.ndarray]  # permanent current limit of each end, A (inf: none in the graph)
    i_columns: tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]  # per end: magnitude, angle
    bus: Bus  # the stations, for the end voltages
    bus_row: tuple[np.ndarray, np.ndarray]
    y: np.ndarray
    b: np.ndarray
    n: np.ndarray
    in_service: np.ndarray  # as the graph has it (both terminals connected): what an estimate assumes
    out_threshold: float = 1.0  # A: a measured end below it carries no current

    @classmethod
    def from_cim(cls, repo, header: PmuHeader, units=None, *, bus: Bus | None = None, measurements: pd.DataFrame | None = None) -> Branch:
        """Every line and two-winding transformer (or those of ``units``: names or mRIDs)."""
        table = pmu_measurements(repo) if measurements is None else measurements
        bus = bus or Bus.from_cim(repo, header, measurements=table)
        params = _parameters(repo)
        if units is not None:
            wanted = set(units)
            params = params[params.index.isin(wanted) | params.name.isin(wanted)]
        mrid = params.index.to_numpy()
        at, limits = Columns(header), current_limits(repo)
        terminals = terminal_table(repo).merge(_node_stations(repo), on="node", how="left")
        terminals = terminals[terminals.equipment.isin(set(mrid))].drop_duplicates(["equipment", "sequence"])
        magnitude = _by(table, ["equipment", "sequence"], "I")
        angle = _by(table, ["equipment", "sequence"], "I_angle")

        def end(k: int):
            these = terminals[terminals.sequence == k].set_index("equipment").reindex(mrid)
            keys = [(m, k) for m in mrid]
            columns = (at(magnitude.reindex(keys)), at(angle.reindex(keys)))
            station = these.station.to_numpy(object)
            V_n = np.where(these.kv.notna(), these.kv, params[f"ratedU{k}"]).astype(float)
            I_n = np.array([limits.get((m, k), np.inf) for m in mrid])
            connected = these.connected.map(lambda c: c is not False and c != "false").to_numpy(bool)
            return station, V_n, I_n, columns, bus.index(station), connected

        (s1, v1, i1, c1, r1, on1), (s2, v2, i2, c2, r2, on2) = end(1), end(2)
        return cls(
            names=params.name.to_numpy(),
            mrid=mrid,
            kind=params.kind.to_numpy(),
            station=(s1, s2),
            V_n=(v1, v2),
            I_n=(i1, i2),
            i_columns=(c1, c2),
            bus=bus,
            bus_row=(r1, r2),
            y=params.y.to_numpy(complex),
            b=params.b.to_numpy(float),
            n=params.n.to_numpy(float),
            in_service=on1 & on2,
        )

    # -- the evaluation everything else reads

    def _measured_currents(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return _phasor(values, *self.i_columns[0]), _phasor(values, *self.i_columns[1])

    def _out(self, I1: np.ndarray, I2: np.ndarray) -> np.ndarray:
        """Measured out: some end measured, and every measured end below the threshold."""
        some = np.isfinite(I1) | np.isfinite(I2)
        quiet = np.fmax(np.abs(I1), np.abs(I2)) < self.out_threshold  # fmax: a NaN end does not count
        return some & quiet

    def _state(self, meas, estimate: bool) -> _State:
        values = values_of(meas)
        V = self.bus.V(values)
        I1, I2 = self._measured_currents(values)
        V_measured, I1_measured, I2_measured = np.isfinite(V), np.isfinite(I1), np.isfinite(I2)
        if estimate:
            V = self._estimate_voltages(V, I1, I2)
            out = self._out(I1, I2) | (~self.in_service & ~(I1_measured | I2_measured))
            m1, m2 = self._model_currents(_at_rows(V, self.bus_row[0]), _at_rows(V, self.bus_row[1]))
            I1 = np.where(I1_measured, I1, np.where(out, 0.0, m1))
            I2 = np.where(I2_measured, I2, np.where(out, 0.0, m2))

        def source(measured: np.ndarray, value: np.ndarray) -> np.ndarray:
            return np.where(measured, MEASURED, np.where(np.isfinite(value), ESTIMATED, MISSING))

        return _State(V, I1, I2, source(V_measured, V), source(I1_measured, I1), source(I2_measured, I2))

    def _model_currents(self, V1_kv: np.ndarray, V2_kv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The currents into each end the pi model gives for these end voltages (line-to-line kV), A."""
        V1 = V1_kv / SQRT3  # phase kV
        V2 = V2_kv / SQRT3 * self.n  # on end 1's side
        b1, b2 = self._shunts()
        I1 = self.y * (V1 - V2) + 1j * b1 * V1
        I2 = (self.y * (V2 - V1) + 1j * b2 * V2) * self.n  # back to end 2's side
        return I1 * 1000.0, I2 * 1000.0  # kA -> A

    def _shunts(self) -> tuple[np.ndarray, np.ndarray]:
        line = self.kind == "ACLineSegment"
        return np.where(line, self.b / 2, self.b), np.where(line, self.b / 2, 0.0)

    def _estimate_voltages(self, V: np.ndarray, I1: np.ndarray, I2: np.ndarray) -> np.ndarray:
        """``V`` with each missing station voltage estimated from a neighbour's, across an in-service
        branch whose current is measured at that neighbour's end; repeated while that fills more."""
        V = np.array(V, dtype=complex)
        b1, b2 = self._shunts()
        for _ in range(len(self.bus.names)):
            filled = False
            for i in np.flatnonzero(self.in_service & (self.bus_row[0] >= 0) & (self.bus_row[1] >= 0)):
                r1, r2, y, n = self.bus_row[0][i], self.bus_row[1][i], self.y[i], self.n[i]
                V1, V2 = V[..., r1] / SQRT3, V[..., r2] / SQRT3 * n  # phase kV, on end 1's side
                i1, i2 = I1[..., i] / 1000.0, I2[..., i] / 1000.0 / n  # kA, on end 1's side
                # Known end 1: I1 = y (V1 - V2) + j b1 V1. Known end 2: I2 = y (V2 - V1) + j b2 V2.
                for row, known, current, shunt, scale in ((r2, V1, i1, b1[i], 1 / n), (r1, V2, i2, b2[i], 1.0)):
                    need = np.isnan(V[..., row]) & np.isfinite(known) & np.isfinite(current)
                    if np.any(need):
                        far = known - (current - 1j * shunt * known) / y
                        V[..., row] = np.where(need, far * SQRT3 * scale, V[..., row])
                        filled = True
            if not filled:
                break
        return V

    # -- what is measured (or, with ``estimate``, estimated)

    def V_from(self, meas, estimate: bool = False) -> np.ndarray:
        """Voltage at end 1, line-to-line kV."""
        return _at_rows(self._state(meas, estimate).V, self.bus_row[0])

    def V_to(self, meas, estimate: bool = False) -> np.ndarray:
        return _at_rows(self._state(meas, estimate).V, self.bus_row[1])

    def I_from(self, meas, estimate: bool = False) -> np.ndarray:
        """Current into the branch at end 1, A."""
        return self._state(meas, estimate).I1

    def I_to(self, meas, estimate: bool = False) -> np.ndarray:
        return self._state(meas, estimate).I2

    def freq_from(self, meas) -> np.ndarray:
        return _at_rows(self.bus.freq(meas), self.bus_row[0])

    def freq_to(self, meas) -> np.ndarray:
        return _at_rows(self.bus.freq(meas), self.bus_row[1])

    def provenance(self, meas, estimate: bool = False) -> dict[str, np.ndarray]:
        """Where each end's voltage and current came from: ``MEASURED``, ``ESTIMATED`` or ``MISSING``
        (``PROVENANCE[code]`` names it), per branch."""
        s = self._state(meas, estimate)
        end = lambda rows: np.where(rows >= 0, s.V_source[..., np.maximum(rows, 0)], MISSING)  # noqa: E731
        return {"V_from": end(self.bus_row[0]), "V_to": end(self.bus_row[1]), "I_from": s.I1_source, "I_to": s.I2_source}

    def voltages(self, meas, estimate: bool = False) -> np.ndarray:
        """Every station's voltage (``bus.names`` order), line-to-line kV: with ``estimate``, the
        missing ones estimated across the branches."""
        return self._state(meas, estimate).V

    # -- what follows from it

    def S_from(self, meas, estimate: bool = False) -> np.ndarray:
        """Complex power into the branch at end 1, MVA."""
        s = self._state(meas, estimate)
        return SQRT3 * _at_rows(s.V, self.bus_row[0]) * np.conj(s.I1) / 1000.0

    def S_to(self, meas, estimate: bool = False) -> np.ndarray:
        s = self._state(meas, estimate)
        return SQRT3 * _at_rows(s.V, self.bus_row[1]) * np.conj(s.I2) / 1000.0

    def P_from(self, meas, estimate: bool = False) -> np.ndarray:
        return self.S_from(meas, estimate).real

    def P_to(self, meas, estimate: bool = False) -> np.ndarray:
        return self.S_to(meas, estimate).real

    def Q_from(self, meas, estimate: bool = False) -> np.ndarray:
        return self.S_from(meas, estimate).imag

    def Q_to(self, meas, estimate: bool = False) -> np.ndarray:
        return self.S_to(meas, estimate).imag

    def losses(self, meas, estimate: bool = False) -> np.ndarray:
        """Complex power the branch consumes, MVA: what flows in at both ends."""
        return self.S_from(meas, estimate) + self.S_to(meas, estimate)

    def loading(self, meas, estimate: bool = False) -> np.ndarray:
        """The larger end's current over that end's permanent limit (NaN where the graph has none, or
        neither end's current is known)."""
        s = self._state(meas, estimate)
        with np.errstate(invalid="ignore"):
            ratio = np.fmax(np.abs(s.I1) / self.I_n[0], np.abs(s.I2) / self.I_n[1])
        return np.where(np.isfinite(self.I_n[0]) | np.isfinite(self.I_n[1]), ratio, np.nan)

    def disconnected(self, meas) -> np.ndarray:
        """Measured out: some end's current is measured, and every measured end carries none. A branch
        no current is measured on is not disconnected: it is ``unobserved``."""
        return self._out(*self._measured_currents(values_of(meas)))

    def unobserved(self, meas) -> np.ndarray:
        """No current measured at either end: whether it is in service, no PMU says."""
        I1, I2 = self._measured_currents(values_of(meas))
        return ~(np.isfinite(I1) | np.isfinite(I2))

    def angle_across(self, meas, estimate: bool = False) -> np.ndarray:
        """The angle between its ends' voltages, degrees, in (-180, 180]."""
        s = self._state(meas, estimate)
        V1, V2 = _at_rows(s.V, self.bus_row[0]), _at_rows(s.V, self.bus_row[1])
        return -np.degrees(np.angle(V2 * self.n / V1))

    def connectable(self, meas, max_angle_deg: float = 30.0, estimate: bool = False) -> np.ndarray:
        """Measured out, and its ends' voltages close enough in angle to close it again."""
        return self.disconnected(meas) & (np.abs(self.angle_across(meas, estimate)) < max_angle_deg)

    # -- the model

    def I_model(self, meas, estimate: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """The currents into each end that the pi model gives for the end voltages, A."""
        s = self._state(meas, estimate)
        return self._model_currents(_at_rows(s.V, self.bus_row[0]), _at_rows(s.V, self.bus_row[1]))

    def residual(self, meas) -> np.ndarray:
        """How far the measured currents are from the model's for the measured voltages, relative to
        the larger: a wrong parameter, a wrong mapping or a bad measurement, if the branch is in
        service. NaN where it cannot be told."""
        m1, m2 = self.I_model(meas)
        I1, I2 = self._measured_currents(values_of(meas))
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.fmax(np.abs(I1 - m1), np.abs(I2 - m2)) / np.fmax(np.abs(I1), np.abs(I2))

    def net_injection(self, meas, estimate: bool = False) -> np.ndarray:
        """Each station's net injection, MVA, from the branch flows (Kirchhoff: what flows into the
        branches at a station is what its generators, loads and shunts put in). NaN for a station
        where a branch's flow is unknown; a branch measured out counts as none. Only branches in
        this model count: build it with ``units=None`` for this to be right."""
        s = self._state(meas, estimate)
        out = self._out(*self._measured_currents(values_of(meas)))
        S = np.zeros(np.shape(s.V), dtype=complex)
        for rows, V, I in ((self.bus_row[0], _at_rows(s.V, self.bus_row[0]), s.I1), (self.bus_row[1], _at_rows(s.V, self.bus_row[1]), s.I2)):
            flow = np.where(out, 0.0, SQRT3 * V * np.conj(I) / 1000.0)
            ok = rows >= 0
            np.add.at(S, (..., rows[ok]), flow[..., ok])  # NaN stays NaN
        return S


def _node_stations(repo) -> pd.DataFrame:
    """Each connectivity node's station and kV (through its voltage level)."""
    nodes = repo.query(L.ConnectivityNodes).to_dataframe(node=F.mRID, level=F.ConnectivityNodeContainer.mRID)
    return nodes.merge(_voltage_levels(repo)[["level", "station", "kv"]], on="level", how="left")[["node", "station", "kv"]]


def _parameters(repo) -> pd.DataFrame:
    """Each branch by mRID: ``name``, ``kind``, its pi model in physical units referred to end 1 (``y``
    S, ``b`` S, ``n``), and its ends' rated kV (``ratedU1``, ``ratedU2``; a line's from its base voltage)."""
    lines = repo.query(L.ACLineSegments).to_dataframe(mRID=F.mRID, name=F.name, r=F.r, x=F.x, bch=F.bch, kv=F.BaseVoltage.nominalVoltage)
    rows = {}
    for line in lines.itertuples():
        z = complex(_num(line.r), _num(line.x))
        kv = _num(line.kv, np.nan)
        rows[line.mRID] = dict(name=line.name, kind="ACLineSegment", y=1 / z if z else np.nan, b=_num(line.bch), n=1.0, ratedU1=kv, ratedU2=kv)
    names = dict(repo.query(L.PowerTransformers).to_dataframe(mRID=F.mRID, name=F.name).values)
    ends = repo.query(L.PowerTransformerEnds).to_dataframe(
        transformer=F.PowerTransformer.mRID, end=F.endNumber, r=F.r, x=F.x, b=F.b, ratedU=F.ratedU
    )
    for mrid, these in ends.groupby("transformer"):
        if len(these) != 2:
            continue  # a three-winding transformer: not in this sketch
        these = these.sort_values("end")
        U1, U2 = (_num(u, np.nan) for u in these.ratedU)
        n = U1 / U2
        z = sum(complex(_num(r), _num(x)) * (1.0 if k == 0 else n**2) for k, (r, x) in enumerate(zip(these.r, these.x, strict=True)))
        rows[mrid] = dict(name=names.get(mrid), kind="PowerTransformer", y=1 / z if z else np.nan, b=sum(_num(b) for b in these.b), n=n, ratedU1=U1, ratedU2=U2)
    return pd.DataFrame.from_dict(rows, orient="index", columns=["name", "kind", "y", "b", "n", "ratedU1", "ratedU2"])
