from pswamp_modules.state_estimator.component_models import (
    values_of,
    pmu_measurements,
    PmuFrame,
    Bus,
    Branch,
    Columns,
    PROVENANCE,
)
import pandas as pd
import numpy as np
from lazycim import L, F



# %% Settings for the demonstration
import matplotlib.pyplot as plt
from lazycim.sim.tops_live import LiveTops

from pswamp_core.cim import SAMPLE_GRID, CimSettings, connect_reader
from pswamp_modules.rtsim_from_cim.engine import EXPORT, SimEngine
from pswamp_modules.rtsim_from_cim.pmu import pmu_layout, pmu_values, read_measurements

# CIM_PATH = SAMPLE_GRID
from pathlib import Path
CIM_PATH = Path("./grids/nordic44")

# TRIP = "Verdal trafostasjon 300 kV - Surna koblingsstasjon 300 kV 1"
TRIP = "300SIMA-BLAFALLI"

# TRIP = "Alpha-Gamma 400 kV line"  # a line of the model, disconnected AT seconds in
SECONDS, AT, DT, RATE = 6.0, 2.0, 0.01, 50
UNMEASURED_LINE = "420SYLLING-SKIEN"  # its currents taken out of the frames
UNMEASURED_STATION = "MO_300"  # its voltage taken out of the frames
SAVE: str | None = None  # write the plot to this PNG instead of showing it

# %% Simulate, and turn the snapshots into the frames the live source would send
repo = connect_reader(CimSettings(cim_path=CIM_PATH))

repo.query(L.ACLineSegment).to_dataframe(name=F.name)
repo.query(L.ConnectivityNode).to_dataframe(name=F.name)

live = LiveTops.from_repo(repo, dt=DT, **EXPORT)
engine = SimEngine(live.built.model, dt=DT, events=live.built.events)
layout = pmu_layout(read_measurements(repo), engine, live.sim.ids, RATE)
steps = round(1 / (RATE * DT))
snapshots = [engine.snapshot()]
while snapshots[-1].sim_time_s < SECONDS:
    if abs(snapshots[-1].sim_time_s - AT) < steps * DT / 2:
        engine.apply(("event", ("lines", "Line", TRIP, "disconnect", {})))
    snapshots.append(engine.step(steps))
t = np.array([s.sim_time_s for s in snapshots])
header = layout.header
frames = values_of([pmu_values(layout, s) for s in snapshots])  # samples x columns
print(f"{len(t)} frames of {header.n_columns} columns")

# %% The models, from the graph and the header
table = pmu_measurements(repo)
bus = Bus.from_cim(repo, header, measurements=table)
branch = Branch.from_cim(repo, header, bus=bus, measurements=table)
print(f"{len(bus.names)} stations: {', '.join(bus.names)}; measured: {', '.join(bus.names[bus.measured])}")
print(f"{len(branch.names)} branches: {', '.join(branch.names)}")

# One frame, as a module would see it live ...
frame = PmuFrame(timestamp=pd.Timestamp.now(tz="UTC").to_pydatetime(), mRID="demo", header=header, values=pmu_values(layout, snapshots[0]))
print("\nbefore the trip, one frame (the transformer's currents are not measured: NaN):")
print(pd.DataFrame({
    "branch": branch.names, "P_from (MW)": branch.P_from(frame), "P_to (MW)": branch.P_to(frame),
    "losses (MW)": branch.losses(frame).real, "loading": branch.loading(frame), "model residual": branch.residual(frame),
}).round(4).to_string(index=False))  # fmt: skip

# ... and the whole run at once: the same calls on samples x columns.
last = frames[-1]
print(f"\nafter the trip: disconnected {list(branch.names[branch.disconnected(last)])}, unobserved {list(branch.names[branch.unobserved(last)])}")

# %% Take measurements away, and estimate them back
degraded = frames.copy()
drop = table[
    ((table.equipment_name == UNMEASURED_LINE) & table.quantity.isin(["I", "I_angle"]))
    | ((table.station == UNMEASURED_STATION) & table.quantity.isin(["V", "V_angle"]))
]
degraded[:, Columns(header)(drop.mRID)] = np.nan
print(f"\ntaken away: {', '.join(drop.name)}")

codes = branch.provenance(degraded[-1], estimate=True)
estimated = pd.DataFrame({
    "branch": branch.names,
    **{f"{key} is": PROVENANCE[code] for key, code in codes.items()},
    "P_from measured (MW)": branch.P_from(frames[0]),
    "P_from no estimate": branch.P_from(degraded[0]),
    "P_from estimated": branch.P_from(degraded[0], estimate=True),
})  # fmt: skip
with pd.option_context("display.width", 250, "display.max_columns", None):
    print(estimated.round(2).to_string(index=False))
injection = pd.DataFrame({
    "station": bus.names,
    "P measured (MW)": branch.net_injection(frames[0]).real,
    "P no estimate": branch.net_injection(degraded[0]).real,
    "P estimated": branch.net_injection(degraded[0], estimate=True).real,
})  # fmt: skip
print(f"\nnet injection per station, before the trip:\n{injection.round(2).to_string(index=False)}")

# The estimates against the truth over the whole run: the voltage at the station, and the transformer's
# current (no PMU measures it) against the simulation's own.
station = bus.index([UNMEASURED_STATION])[0]
V_est = branch.voltages(degraded, estimate=True)[:, station]
V_true = bus.V(frames)[:, station]
trafo = int(np.flatnonzero(branch.kind == "PowerTransformer")[0]) if np.any(branch.kind == "PowerTransformer") else None
print(f"\n{UNMEASURED_STATION}: largest error of the estimated voltage {np.nanmax(np.abs(V_est - V_true) / np.abs(V_true)):.2e} (relative)")
if trafo is not None:
    I_est = branch.I_from(degraded, estimate=True)[:, trafo]
    I_true = np.array([s.t_from_ka[0] for s in snapshots]) * 1000.0
    print(f"{branch.names[trafo]}: largest error of the estimated current {np.nanmax(np.abs(I_est - I_true) / np.abs(I_true)):.2e} (relative)")

# %% Plot
line = int(np.flatnonzero(branch.names == UNMEASURED_LINE)[0])
figure, (flows, voltage) = plt.subplots(2, 1, sharex=True, figsize=(9, 6))
flows.plot(t, branch.P_from(frames)[:, line], linewidth=2.5, color="lightgrey", label="measured")
flows.plot(t, branch.P_from(degraded, estimate=True)[:, line], linewidth=0.9, linestyle="--", label="estimated, unmeasured")
flows.legend(fontsize="small")
flows.set(ylabel="P into end 1 (MW)", title=f"{UNMEASURED_LINE} with no current measured, {UNMEASURED_STATION} no voltage; {TRIP} out at {AT:g} s")
voltage.plot(t, np.abs(V_true), linewidth=2.5, color="lightgrey", label="measured")
voltage.plot(t, np.abs(V_est), linewidth=0.9, linestyle="--", label="estimated, unmeasured")
voltage.set(xlabel="simulated time (s)", ylabel=f"|V| {UNMEASURED_STATION} (kV)")
for axes in (flows, voltage):
    axes.axvline(AT, color="grey", linestyle="--")
figure.tight_layout()
if SAVE:
    figure.savefig(SAVE, dpi=120)
    print(f"wrote {SAVE}")
else:
    plt.show()
