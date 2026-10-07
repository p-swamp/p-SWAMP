# Modules

The analysis modules of the p-SWAMP server data architecture, **one Python
project per module**. `doc/server-data-architecture.md` describes the
architecture; `doc/module-cookbook.md` is the recipe for a new module.

| Folder | Distribution | Package | Reads | Emits |
|---|---|---|---|---|
| [`frame-stats/`](frame-stats/) | `pswamp-frame-stats` | `pswamp_modules.frame_stats` | `PmuFrame` | `FrameStatsResult` |
| [`excursion/`](excursion/) | `pswamp-excursion` | `pswamp_modules.excursion` | `FrameStatsResult` | `ExcursionResult`, `PauseCommand` |
| [`range-summary/`](range-summary/) | `pswamp-range-summary` | `pswamp_modules.range_summary` | (commands only) | `RangeSummaryResult` |

Each module folder holds exactly:

```
modules/<name>/
  pyproject.toml   the project; its entry point in "pswamp.modules"
  README.md        what it reads, emits and accepts; its parameters
  src/pswamp_modules/<pkg>/   the code (no src/pswamp_modules/__init__.py:
                              pswamp_modules is a PEP 420 namespace)
  tests/           its tests
```

## Rules

- **A module depends on `pswamp-core` and `pswamp-models`** (plus any
  third-party library it declares) **and nothing else in this repo.** It never
  imports the web backend or the desktop package. Its messages live in
  `pswamp_models.<pkg>`, never in the module.
- **`pswamp-core` imports nothing from here.**
- **A module folder holds only module code.** The pipelines and the example
  sources are in the transitional `legacy/pswamp-wiring/` until they are
  replaced.

`tools/tests/test_tools_layering.py` checks all three over every
`modules/*/pyproject.toml`.

## Commands

```
uv run pswamp test module frame-stats     # one module's tests (folder or entry-point name)
uv run pswamp test server                 # every suite, these included
uv run pswamp new module <slug> "<Label>" # a new module project, its models, pipeline, api and page
```
