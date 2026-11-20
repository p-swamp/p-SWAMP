"""Prototyping the State Estimator: a grid from a CIM folder, an event, the module over the PMU frames,
and a look around the ``StateEstimate`` it publishes. Run it cell by cell (``# %%``) in an editor.

    uv run --package pswamp-state-estimator --extra rtsim python modules/state-estimator/examples/explore_state_estimate.py

Paths are relative to the repo root; run it from there.
"""

# %% Settings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from pswamp_models.pmu import PmuFrame
from pswamp_models.rtsim import TripBranchCommand
from pswamp_models.state_estimator import StateEstimate
from pswamp_modules.state_estimator import StateEstimatorModule
from pswamp_modules.state_estimator.component_models import Bus, Columns, pmu_measurements, values_of
from pswamp_modules.state_estimator.offline import Grid, simulate

CIM_PATH: Path | None = Path("grids/nordic44")  # a folder of CGMES files (*.xml); None: LazyCIM's Nordic44
SECONDS = 8.0  # simulated, which is real time
TRIP_AT, TRIP_LINE = 3.0, "300SIMA-BLAFALLI"  # a line of the model, tripped TRIP_AT s in
PERIOD = 0.1  # s of frame time between two estimates; 0: every frame
UNMEASURED_STATION = "MO_300"  # its PMU voltage is taken out of the frames below, then estimated back

# %% Load the grid: an embedded store, given measurements (and dynamics) where it has none
grid = Grid.load(CIM_PATH if CIM_PATH and CIM_PATH.exists() else None)
repo = grid.repository()
table = pmu_measurements(repo)  # one row per PMU Analog of the graph
print(f"{grid.added} measurements added; {len(table)} PMU measurements, {table.station.nunique()} stations")
table[["name", "station", "quantity", "unit", "equipment_name"]].head(10)

# %% The event: any of the simulations commands (pswamp_models.rtsim) at a simulated time.
# Others: FaultAndClearCommand(mRID=line, end=1, clear_ms=100), LoadStepCommand(mRID=load, p_mw=...),
# OperateSwitchCommand(mRID=breaker, open=True), ShortCircuitCommand(mRID=node), ...
events = [(TRIP_AT, TripBranchCommand(mRID=grid.mrid(TRIP_LINE, "ACLineSegment")))]

# %% Simulate, feeding every PMU frame to the estimator as a host would
estimator = StateEstimatorModule(period=PERIOD)
run = simulate(grid, [estimator], SECONDS, events)
print(f"{len(run.frames)} frames, {len(run.results(estimator)[0])} estimates")
for t, event in run.events:
    print(f"t={t:5.2f} s: {event.kind} {event.mRID} ({event.cause})")

# %% One result: the envelope (when, who, with which settings) around the StateEstimate
t_est, estimates = run.results(estimator)  # times (s from the first frame) and bodies
_, envelope = run.published[estimator.name][0]
print(f"{type(envelope).__name__} at {envelope.timestamp}, from {envelope.app.name}, {envelope.parameters}")

estimate: StateEstimate = envelope.result
print(f"grid {estimate.cimReferenceId}: {estimate.measured} stations measured, {estimate.estimated} estimated")
pd.DataFrame([bus.model_dump() for bus in estimate.buses])

# %% The whole run as one long table: one row per estimate and station
estimates_df = pd.DataFrame(
    [{"t": t, **bus.model_dump()} for t, e in zip(t_est, estimates) for bus in e.buses]
)
v_pu = estimates_df.pivot(index="t", columns="station", values="v_pu")
p_mw = estimates_df.pivot(index="t", columns="station", values="p_mw")
estimates_df.groupby("station").source.agg(lambda s: s.value_counts().to_dict())

# %% Before and after the event: which stations moved the most
before, after = v_pu.loc[:TRIP_AT].iloc[-1], v_pu.iloc[-1]
change = pd.DataFrame({
    "v_pu before": before,
    "v_pu after": after,
    "dV (p.u.)": after - before,
    "dP (MW)": p_mw.iloc[-1] - p_mw.loc[:TRIP_AT].iloc[-1],
})  # fmt: skip
change.reindex(change["dV (p.u.)"].abs().sort_values(ascending=False).index).round(4).head(10)

# %% A sanity check: generation less load should sum to the losses (small, positive)
total = p_mw.sum(axis=1, min_count=1)
print(f"sum of net injections: {total.iloc[0]:.1f} MW before, {total.iloc[-1]:.1f} MW after")

# %% Re-run the module offline on the stored frames, with a PMU taken away: no new simulation
drop = table[(table.station == UNMEASURED_STATION) & table.quantity.isin(["V", "V_angle"])]
_columns: dict[str, np.ndarray] = {}


def degrade(frame: PmuFrame) -> PmuFrame:
    """``frame`` without the measurements in ``drop`` (null, as a PMU that sent nothing)."""
    cols = _columns.setdefault(frame.header.header_id, Columns(frame.header)(drop.mRID))
    values = list(frame.values)
    for c in cols[cols >= 0]:
        values[c] = None
    return frame.model_copy(update={"values": values})


rerun = StateEstimatorModule(period=PERIOD)
rerun.cim_repo = grid.repository()
# run() is what a host would publish: [] for a frame not due
t_deg, degraded = zip(*[(t, r.result) for t, f in zip(run.t, run.frames) for r in rerun.run(degrade(f))])
print(f"taken away: {', '.join(drop.name)}; {len(degraded)} estimates")
print([(b.station, b.source, b.v_pu) for b in degraded[0].buses if b.station == UNMEASURED_STATION])

# %% Estimated against measured, for that station
pick = lambda es: [next(b for b in e.buses if b.station == UNMEASURED_STATION) for e in es]  # noqa: E731
measured = pd.DataFrame([b.model_dump() for b in pick(estimates)], index=t_est)
estimated = pd.DataFrame([b.model_dump() for b in pick(degraded)], index=list(t_deg))
comparison = measured[["v_kv", "angle_deg"]].join(estimated[["v_kv", "angle_deg", "source"]], lsuffix=" measured", rsuffix=" estimated")
error = (comparison["v_kv estimated"] - comparison["v_kv measured"]).abs() / comparison["v_kv measured"]
print(f"{UNMEASURED_STATION}: largest relative error of |V| {error.max():.2e}")
comparison.describe()

# %% The truth straight from the frames, through the same Bus model the estimator builds
bus = Bus.from_cim(repo, run.frames[0].header, measurements=table)
V = bus.V(values_of([f.values for f in run.frames]))  # frames x stations, complex kV
truth = pd.Series(np.abs(V[:, bus.index([UNMEASURED_STATION])[0]]), index=run.t, name="|V| (kV)")

# %% Plot
figure, (voltages, station) = plt.subplots(2, 1, sharex=True, figsize=(9, 6))
voltages.plot(v_pu.index, v_pu.values, linewidth=0.7)
voltages.set(ylabel="estimated V (p.u.)", title=f"{len(v_pu.columns)} stations; {TRIP_LINE} tripped at {TRIP_AT:g} s")
station.plot(truth.index, truth.values, linewidth=2.5, color="lightgrey", label="every frame, measured")
station.plot(comparison.index, comparison["v_kv estimated"], linestyle="--", label="estimated, PMU taken away")
station.set(xlabel="simulated time (s)", ylabel=f"|V| {UNMEASURED_STATION} (kV)")
station.legend(fontsize="small")
for axes in (voltages, station):
    for t, _ in run.events:
        axes.axvline(t, color="grey", linestyle="--")
figure.tight_layout()
plt.show()
