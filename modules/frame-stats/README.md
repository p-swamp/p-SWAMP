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

`examples/rtsim_frame_stats.py` runs the module over the **live grid simulation**
(`rtsim-from-cim`) of Nordic44, held in an embedded Oxigraph store of the script's
own: no server, no Docker, no p-SWAMP store. A few seconds in it edits the graph
(the largest load steps up, or `--breaker <mRID>` opens a breaker) and plots the
frequency and the mean voltage as the simulation follows. It shows three things
a script can do with any module:

- **bring its own LazyCIM store**: any `CIMRepository` will do; this one is
  LazyCIM's Nordic44 demo model in pyoxigraph, and `pswamp_core.cim.prepare`
  gives it what p-SWAMP needs (machine dynamics, PMU Analogs);
- **use another module by name, never by import**:
  `pswamp_core.scripts.source("rtsim-from-cim", repo=repo)`; the `rtsim` extra
  installs it (with pyoxigraph and matplotlib), and the module's own
  dependencies stay as they are;
- **steer the simulation by editing the graph**, through a second repository
  over the same store. That store has no version stamp, so the simulation looks
  for edits every couple of seconds.

```
uv run --package pswamp-frame-stats --extra rtsim python modules/frame-stats/examples/rtsim_frame_stats.py --save fs.png
```

It takes about half a minute: a second to load the grid, a second to prepare
it, a few to start the simulation, then the run itself. Nordic44 is downloaded
by LazyCIM once (`python -m lazycim.demo` fills its cache ahead, for a machine
that will be offline).

## Tests

`uv run pswamp test module frame-stats` (also part of `uv run pswamp test server`).
