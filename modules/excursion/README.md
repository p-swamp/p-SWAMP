# excursion

`pswamp-excursion`, package `pswamp_modules.excursion`, class
`ExcursionModule`, entry point `excursion` (group `pswamp.modules`).

Chained onto [frame-stats](../frame-stats/): it reads what that module
publishes and reports whether the mean frequency is inside a band around
nominal, counting the excursions out of it. With auto-pause on, leaving the
band also pauses the player.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | `FrameStatsResult` | `frame.stats.result` | `pswamp_models.frame_stats` |
| Emits | `ExcursionResult` (body `Excursion`) | `excursion.result` | `pswamp_models.excursion` |
| Emits | `PauseCommand`, on leaving the band with auto-pause on | `pause` | `pswamp_models.player` |
| Accepts | `AutoPauseCommand(enabled)`: turn pausing on excursion on or off | `auto.pause` | `pswamp_models.excursion` |

**Parameters:** `nominal_hz` = 50.0 and `band_hz` = 0.005 (module constants
`NOMINAL_HZ`, `BAND_HZ`, reported in `parameters`). A result whose mean
frequency is `None` produces nothing. Auto-pause starts off.

## From a script

```python
from pswamp_models.excursion import AutoPauseCommand
from pswamp_modules.excursion import ExcursionModule

excursion = ExcursionModule()
excursion.run_command(AutoPauseCommand(enabled=True))
for message in excursion.run(stats_result):   # an ExcursionResult, and a PauseCommand on leaving the band
    print(message)
```

## Tests

`uv run pswamp test module excursion` (also part of `uv run pswamp test server`).
