# pswamp-models

Every message that crosses a topic, a socket or a process boundary in the
p-SWAMP server data architecture, as pydantic models. One package per
producer: a message's class lives with whoever publishes it, and every
consumer (the core, other modules, the web backend, the api contract) imports
it from here, never from the producer's code.

| Package | Messages |
|---|---|
| `pswamp_models.common` | `DataModel`, `Command`, `ResultEnvelope`, `AppIdentity`, `ErrorEvent`, `PipelineClosed` |
| `pswamp_models.player` | `PlayerCommand`, `PlayCommand`, `PauseCommand`, `StepCommand`, `SeekCommand`, `SpeedCommand`, `SwitchSourceCommand`, `PlayerStatus` |
| `pswamp_models.pmu` | `PmuHeader`, `PmuFrame` |
| `pswamp_models.remote_data` | `RemoteDataQuery`, `RemoteDataResult` |
| `pswamp_models.frame_stats` | `FrameStats`, `FrameStatsResult` |
| `pswamp_models.excursion` | `Excursion`, `ExcursionResult`, `AutoPauseCommand` |
| `pswamp_models.range_summary` | `RangeSummary`, `RangeSummaryResult`, `SummarizeRangeCommand` |

- A new module's messages go in a new package here (`uv run pswamp new module` writes it);
  see `doc/module-cookbook.md`. Class names are topic names, so renaming one is a wire change.
- Source: `src/pswamp_models/`
- Depends on pydantic only, and imports nothing else from this repo.
- Tests: `tests/`, run by `uv run pswamp test server`
