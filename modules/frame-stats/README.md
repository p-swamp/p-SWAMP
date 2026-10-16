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

## Examples

`examples/plot_frame_stats.py` runs the module over a synthetic frequency dip
and plots the mean, min and max frequency. matplotlib comes from the project's
`examples` extra (the module itself does not need it):

    uv run --package pswamp-frame-stats --extra examples python modules/frame-stats/examples/plot_frame_stats.py
    uv run --package pswamp-frame-stats --extra examples python modules/frame-stats/examples/plot_frame_stats.py --save fs.png

Without the extra, `uv run python modules/frame-stats/examples/plot_frame_stats.py`
prints the statistics instead. To run it over the real sample recording instead of
synthetic frames, see `modules/sample-replay/examples/replay_stats.py`.

## Tests

`uv run pswamp test module frame-stats` (also part of `uv run pswamp test server`).
