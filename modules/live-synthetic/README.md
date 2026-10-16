# live-synthetic

`pswamp-live-synthetic`, package `pswamp_modules.live_synthetic`, class
`LiveSynthetic`, entry point `live-synthetic` (group `pswamp.modules`).

A **source**: it has no inputs, it produces. A synthetic *live* feed: the
sample recording's 60 frames (five stations, 20 Hz, spanning a line trip), taken
in turn and stamped with the current time at the recording's own rate, so the
trip comes round every three seconds. No broker behind it. A live source has no
`coverage`, and it is not playable: it cannot be sought, paused or replayed, and
a run follows it as it arrives.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | nothing | | |
| Emits | `PmuFrame` (mRID `n44-live`) | `pmu.frame` | `pswamp_models.pmu` |
| Accepts | no command | | |

**Settings:** `path`, another sample file (same format as sample-replay's)
whose rows are cycled; default the bundled copy. A deployment sets
`{SOURCE}_PATH` (`LIVE_PATH` for a source named `live`; the k8s example mounts one
from a ConfigMap); a script passes `LiveSynthetic(path="mine.txt")`.

## From a script

`read(start, end)` is the synchronous form (`aread` is what the host uses; it
runs without a thread). Without an `end` it never stops, so a script bounds it:

```python
from datetime import timedelta

from pswamp_core.util.time import utcnow
from pswamp_modules.live_synthetic import LiveSynthetic

for frame in LiveSynthetic().read(end=utcnow() + timedelta(seconds=2)):
    print(frame.timestamp, frame.values[2])
```

Called from inside a running event loop (a notebook), `read` raises a clear
`RuntimeError`: use `async for frame in source.aread(...)` there.

## Examples

`examples/tail_live.py` prints two seconds of the feed:

    uv run python modules/live-synthetic/examples/tail_live.py

## Tests

`uv run pswamp test module live-synthetic` (also part of `uv run pswamp test server`).
