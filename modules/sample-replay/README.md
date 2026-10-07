# sample-replay

`pswamp-sample-replay`, package `pswamp_modules.sample_replay`, class
`SampleReplay`, entry point `sample-replay` (group `pswamp.modules`).

A **source**: it has no inputs, it produces. The bundled Nordic 44 sample
recording (`sample_data.txt`, in the package): five stations at 20 Hz for three
seconds, 60 frames spanning a line trip, as `PmuFrame`s sharing one header.
It is a *history* (it has a `coverage`, `[0.05 s, 3.05 s)` after 2026-01-01) and
*playable* (the player controls apply: play, pause, step, seek, speed, loop).

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | nothing | | |
| Emits | `PmuFrame` (the primary, paced stream) | `pmu.frame` | `pswamp_models.pmu` |
| Accepts | `PlayCommand`, `PauseCommand`, `StepCommand`, `SeekCommand`, `SpeedCommand` | | `pswamp_models.player` |

**Settings:** `path`, another file in the same one-line-per-station format
(default: the bundled one). A deployment sets `{SOURCE}_PATH` (`SAMPLE_PATH` for
a source named `sample`); a script passes `SampleReplay(path="mine.txt")`.

## From a script

`read` is a plain generator: no server, no transport, no event loop.

```python
from pswamp_modules.frame_stats import FrameStatsModule
from pswamp_modules.sample_replay import SampleReplay

stats = FrameStatsModule()
results = [stats.run_one(frame).result for frame in SampleReplay().read()]
```

`read(start, end)` takes a half-open range, `coverage()` says what the
recording holds. The host calls `aread` / `acoverage`, derived from the same code.

## Examples

`examples/replay_stats.py` is the repo's canonical script: a source read with a
`for` loop, a module called like a function, and a plot, top to bottom with no
event loop. It replays the recording through frame-stats and plots the mean, min
and max frequency. matplotlib and the frame-stats module come from the project's
`examples` extra, which the source itself does not need:

    uv run --package pswamp-sample-replay --extra examples python modules/sample-replay/examples/replay_stats.py
    uv run --package pswamp-sample-replay --extra examples python modules/sample-replay/examples/replay_stats.py --save fs.png

## Tests

`uv run pswamp test module sample-replay` (also part of `uv run pswamp test server`).
