# frame-stats

`pswamp-frame-stats`, package `pswamp_modules.frame_stats`, class
`FrameStatsModule`, entry point `frame-stats` (group `pswamp.modules`).

Per-frame statistics of a PMU stream: mean, min and max frequency, the voltage
angle spread and the mean voltage magnitude over the stations of each frame.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | `PmuFrame` | `pmu.frame` | `pswamp_models.pmu` |
| Emits | `FrameStatsResult` (body `FrameStats`) | `frame.stats.result` | `pswamp_models.frame_stats` |
| Accepts | no command | | |

**Parameters:** none to set. It finds its columns (`f`, `V_Magnitude`,
`V_Angle`) in the frame's own header, and re-derives them only when the
header's `header_id` changes, so it needs no setup. `parameters` reports the
`header_id` and the stations in use. Null values are skipped; a frame with no
frequency value gives `None` statistics.

## From a script

No server, transport or event loop: `process` is plain synchronous code, and
`run_one` returns the one result the module publishes for a frame.

```python
from pswamp_modules.frame_stats import FrameStatsModule

stats = FrameStatsModule()
result = stats.run_one(frame)          # a FrameStatsResult
result.result.mean_frequency_hz
```

## Tests

`uv run pswamp test module frame-stats` (also part of `uv run pswamp test server`).
