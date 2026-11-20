# state-estimator

`pswamp-state-estimator`, package `pswamp_modules.state_estimator`, class `StateEstimatorModule`,
entry point `state-estimator` (group `pswamp.modules`).

The State Estimator module. Every `period` seconds of frame time, it reports the state of the grid:
each station's voltage phasor and net injection.

For now this is a **dummy** estimator: it assumes the PMUs measure what the state needs. A station's
voltage is its PMU's, or is estimated across a branch from a measured neighbour (the pi model in
`component_models.py`). Its injection is the sum of its branches' flows. Branch flows are left out of
the message because they follow from the voltages and the graph's branch parameters.

| | Message | Defined in |
|---|---|---|
| Reads | `PmuFrame`, with `header.analog` (the CIM graph's PMU Analogs), and the CIM graph | `pswamp_models.pmu` |
| Emits | `StateEstimatorResult` (body `StateEstimate`, one `BusEstimate` per station) | `pswamp_models.state_estimator` |
| Accepts | no command | |

Per station (voltage level, named `<substation>_<kV>` as the stream names it): `v_kv`, `v_pu`,
`angle_deg` (as the PMUs measure it, not against a slack bus), `p_mw` and `q_mvar` (injected into the
branches: generation less load), and `source` (`measured`, `estimated`, `missing`). A value nothing
tells is null.

**Parameters:** `period` (s, default 1.0; 0 estimates every frame). A frame whose columns name no PMU
Analog of the graph publishes nothing. So does `live-synthetic`, the pipeline file's default source:
the estimator needs the live grid simulation (`rtsim-from-cim`) or another source whose frames are
tied to the graph.

The estimate is published on the transport only. Nothing is written to the CIM graph. `src/pswamp_modules/state_estimator/SV.md` says
how the graph's SV profile could follow it.

## From a script

No server, transport or event loop: `process` is plain synchronous code.

```python
from pswamp_modules.state_estimator import StateEstimatorModule

module = StateEstimatorModule(period=0)
module.cim_repo = repo                       # hosted, the core connects one
estimate = module.run_one(frame).result      # a StateEstimate
[(b.station, b.v_pu, b.angle_deg) for b in estimate.buses]
```

## Examples

`examples/run_state_estimator.py` runs the module over the live simulation of Nordic44, with a line
trip, and plots every station's estimated voltage:

    uv run --package pswamp-state-estimator --extra rtsim python modules/state-estimator/examples/run_state_estimator.py

`examples/explore_state_estimate.py` is for prototyping, cell by cell (`# %%`). It loads a grid from a CIM
folder, trips a line, and runs the module over the frames. Then it explores the `StateEstimate`: the
envelope, one estimate as a table, the whole run as a table, and the stations that moved most. It also
runs the module again on the stored frames with one station's PMU taken out, and compares the estimate
with the measurement:

    uv run --package pswamp-state-estimator --extra rtsim python modules/state-estimator/examples/explore_state_estimate.py

## Tests

`uv run pswamp test module state-estimator` (also part of `uv run pswamp test server`).
