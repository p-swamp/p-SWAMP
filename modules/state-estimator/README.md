# state-estimator

`pswamp-state-estimator`, package `pswamp_modules.state_estimator`, class `StateEstimatorModule`,
entry point `state-estimator` (group `pswamp.modules`).

The State Estimator module. For each frame it reports the station with the highest
frequency, and that frequency.

| | Message | Defined in |
|---|---|---|
| Reads | `PmuFrame` | `pswamp_models.pmu` |
| Emits | `StateEstimatorResult` (body `StateEstimatorBody`) | `pswamp_models.state_estimator` |
| Accepts | no command | |

**Parameters:** none. A frame with no frequency value publishes nothing.

## From a script

No server, transport or event loop: `process` is plain synchronous code.

```python
from pswamp_modules.state_estimator import StateEstimatorModule

result = StateEstimatorModule().run_one(frame)   # a StateEstimatorResult
result.result.station, result.result.frequency_hz
```

## Examples

`examples/run_state_estimator.py` runs the module over a few synthetic frames:

    uv run python modules/state-estimator/examples/run_state_estimator.py

## Tests

`uv run pswamp test module state-estimator` (also part of `uv run pswamp test server`).
