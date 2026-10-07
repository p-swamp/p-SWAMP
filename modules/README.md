# Modules

The analysis modules of the p-SWAMP server data architecture, **one Python
project per module**. `doc/server-data-architecture.md` describes the
architecture; `doc/module-cookbook.md` is the recipe for a new module.

| Folder | Distribution | Kind | Reads | Emits | Accepts |
|---|---|---|---|---|---|
| [`excursion/`](excursion/) | `pswamp-excursion` | module | `FrameStatsResult` | `ExcursionResult`, `PauseCommand` | `AutoPauseCommand` |
| [`frame-stats/`](frame-stats/) | `pswamp-frame-stats` | module | `PmuFrame` | `FrameStatsResult` | — |
| [`live-synthetic/`](live-synthetic/) | `pswamp-live-synthetic` | source (live, not playable) | — | `PmuFrame` | — |
| [`range-summary/`](range-summary/) | `pswamp-range-summary` | module | — | `RangeSummaryResult` | `SummarizeRangeCommand` |
| [`remote-history/`](remote-history/) | `pswamp-remote-history` | source (history, playable) | — | `PmuFrame` | `PlayCommand`, `PauseCommand`, `StepCommand`, `SeekCommand`, `SpeedCommand` |
| [`sample-replay/`](sample-replay/) | `pswamp-sample-replay` | source (history, playable) | — | `PmuFrame` | `PlayCommand`, `PauseCommand`, `StepCommand`, `SeekCommand`, `SpeedCommand` |

The same as `uv run pswamp modules list`, which shows it for whatever is
installed. A **module** reads message classes from the transport and publishes
others; a **source** (`SourceModule`, `pswamp_core.sources`, a `Module` subclass) reads nothing and
produces data, and is read from a script with a plain
`for frame in SampleReplay().read():`. A history source that mixes in `Playable`
(`pswamp_core.playable`) can also be replayed paced and sought, and answers the
player commands; a live source cannot. A run reads its sources through the
pipeline file (`[[sources]] module = "<entry point>"`); the active one is steered
by the run's `ActiveSource` router.

**Running one from a script** needs no server and no event loop. The canonical
example replays the sample recording through `frame-stats` and plots it:
`sample-replay/examples/replay_stats.py`.

Each module folder holds exactly:

```
modules/<name>/
  pyproject.toml   the project; its entry point in "pswamp.modules"
  README.md        what it reads, emits and accepts; its parameters
  src/pswamp_modules/<pkg>/   the code (no src/pswamp_modules/__init__.py:
                              pswamp_modules is a PEP 420 namespace)
  tests/           its tests
  examples/        runnable scripts using it with no server
```

## Rules

- **A module depends on `pswamp-core` and `pswamp-models`** (plus any
  third-party library it declares) **and nothing else in this repo.** It never
  imports the web backend or the desktop package. Its messages live in
  `pswamp_models.<pkg>`, never in the module.
- **`pswamp-core` imports nothing from here.**
- **A module folder holds only module code.** The pipelines are files in
  `pipelines/<app>.toml` at the repo root, naming modules and sources by entry
  point.

`tools/tests/test_tools_layering.py` checks all three over every
`modules/*/pyproject.toml`.

## Commands

```
uv run pswamp test module frame-stats     # one module's tests (folder or entry-point name)
uv run pswamp test server                 # every suite, these included
uv run pswamp new module <slug> "<Label>" # a new module project, its models, pipeline, api and page
uv run python modules/excursion/examples/count_excursions.py   # an example, no server
uv run --package pswamp-sample-replay --extra examples python modules/sample-replay/examples/replay_stats.py   # the canonical script: source -> module -> plot
uv run --package pswamp-frame-stats --extra examples python modules/frame-stats/examples/plot_frame_stats.py
uv run pswamp modules list                # the table above, for what is installed
```

An example needing a library the module does not (matplotlib, to plot) declares
it as the module's `examples` extra, so it never reaches the image.
