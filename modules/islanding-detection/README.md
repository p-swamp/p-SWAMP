# islanding-detection

`pswamp-islanding-detection`, package `pswamp_modules.islanding_detection`, class `IslandingDetectionModule`,
entry point `islanding-detection` (group `pswamp.modules`).

The Islanding detection module. It keeps the last `window_length_s` seconds of every
station's frequency in a `TimeWindow` (`time_window.py`), and every
`1 / eval_freq` seconds of message time runs `detect_islands` (`core.py`) over
it: stations whose smoothed frequencies stay within `mean_threshold` (RMS) of
each other are one group, and every group but the largest is an island.

Each assessment sets the module's status: `Emergency` when there is an island,
`OK` when there is none. An `AlarmRaiser` (`pswamp_core.alarms`, the desktop's
alarm logic) turns that into `AlarmEvent`s: `init` when an emergency begins,
and `not_critical` once the grid has been whole for `alarm_hold_s`. An
emergency that returns within that time is still the same alarm.

| | Message | Defined in |
|---|---|---|
| Reads | `PmuFrame` | `pswamp_models.pmu` |
| Emits | `IslandingDetectionResult` (body `IslandingDetectionBody`) | `pswamp_models.islanding_detection` |
| Emits | `AlarmEvent` | `pswamp_models.common` |
| Accepts | no command | |

**Parameters:** `window_length_s` (10 s), `eval_freq` (1 per second),
`mean_threshold` (0.05 Hz), `alarm_hold_s` (15 s), all constructor arguments. Nothing is published
until the window has filled; a missing or zero frequency is NaN, and a station
with NaN anywhere in the window is left out of every group. `reset` empties the
window and forgets the active alarm, and a frame with a new layout replaces it.

## From a script

No server, transport or event loop: `process` is plain synchronous code.

```python
from pswamp_models.common import AlarmEvent
from pswamp_modules.islanding_detection import IslandingDetectionModule

module = IslandingDetectionModule()
for frame in frames:
    for message in module.run(frame):      # about once a second
        if isinstance(message, AlarmEvent):
            message.type                   # "init" or "not_critical"
        else:                              # an IslandingDetectionResult
            message.result.islands         # e.g. [["6500", "6700", "6701"]]
            message.result.status          # "Emergency" or "OK"
```

## Examples

`examples/run_islanding_detection.py` runs the module over the synthetic case in `synthetic_cases.py`:

    uv run python modules/islanding-detection/examples/run_islanding_detection.py

`examples/n44_line_trip_tops.py` runs it over a TOPS simulation of Nordic 44,
built from CIM with LazyCIM: its demo model, with machine dynamics and a
governor, exciter and stabilizer per machine. Four lines trip at 15 s, which
islands buses 6500, 6700 and 6701, and reconnect at 35 s. The script declares
its own environment (LazyCIM needs Python 3.12, the workspace is on 3.11), so
it runs with `uv run` alone, and the first run downloads Nordic 44 (CC BY-NC-SA
4.0, Statnett SF):

    uv run modules/islanding-detection/examples/n44_line_trip_tops.py

## Tests

`uv run pswamp test module islanding-detection` (also part of `uv run pswamp test server`).
