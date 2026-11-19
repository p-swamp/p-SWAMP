# Keeping a time window in a module

How a module can keep the last N seconds of measurements, so that its analysis
can look at a window rather than a single frame, and how that window should
behave when the user seeks or steps through a recording.

## A module may keep state

A module is an ordinary Python object, and its host keeps the same instance
for the whole run. Anything stored on `self` is still there on the next
`process` call. The existing modules already rely on this:

- `frame-stats` caches its column indices
  ([module.py](modules/frame-stats/src/pswamp_modules/frame_stats/module.py)).
- `excursion` remembers `self._in_band` to detect a band crossing.

A rolling buffer of recent frames works the same way: a `deque` on `self`.

### Where that state lives, and how long it lasts

- **One instance per run key.** On a recording, every client has its own
  instance and therefore its own buffer. On a live source there is one shared
  instance ([server-data-architecture.md](doc/server-data-architecture.md),
  "modules: one instance per client / one instance, results shared").
- **It is in memory only.** The host drops the instance when the run publishes
  `PipelineClosed`, after five minutes with no input, or when its worker
  restarts. The next frame builds a new instance with an empty buffer. This
  matches the stack's stateless design, so the analysis must cope with a
  window that is only partly full.

## Rules for the buffer

1. **Use the frames' timestamps, never the wall clock.** Trim by
   `frame.timestamp`, so that a replay at 2× speed, a pause or a step still
   sees exactly the window of data it should. Joins follow the same rule.
2. **Store only the columns the analysis needs.** A frame has about 700
   channels. Look the columns up from `frame.header` and clear the buffer when
   `header_id` changes, because the old rows then refer to other columns.
3. **Heavy analysis runs off the event loop.** Set `blocking = True` if the
   work on the window is expensive (module cookbook, "A CPU-heavy module").

## Seeks, loops and steps

### What the module sees

The module **never receives** the playback commands. `Play`, `Pause`, `Step`,
`Seek` and `Speed` go to the run's `ActiveSource` router and from there to the
player (one receiver per command class). The module only sees the effect: the
frames' timestamps.

| Action | What arrives at the module |
|---|---|
| Play | Frames with increasing timestamps |
| Step back, `n = -k` | **One** frame, about k frame intervals earlier than the last one ([playable.py](core/src/pswamp_core/playable.py), `_pl_step`) |
| Several single steps back | One frame per step, each earlier than the one before |
| Seek or loop backwards | A frame earlier than the last one, then play continues from there |
| Seek forward, or pacing dropping frames | A frame later than expected: a gap in the buffer |

### Trim instead of clearing

When time goes backwards, **drop every buffered row at or after the new
timestamp** rather than clearing the whole buffer. After a short step back the
remaining rows are exactly the history that leads up to the new frame, so the
result is the same as when that frame first played forward. A jump to before
everything in the buffer drops all of it, which is the same as clearing.

### Keep a margin

Trimming removes data only from the newest end. The oldest end stays where
the last forward frame left it, so each step back makes the window shorter:
after stepping back 2 s, a 10 s window covers only 8 s.

The fix is to **keep more than you analyse**: buffer the window plus a margin,
and analyse only the last `WINDOW` up to the current frame. A step back of up
to `MARGIN` then still gives a full window. Memory is cheap (at 50 Hz and a
few columns, 15 s is 750 small rows per client), so choose a margin as long as
anyone will realistically step back. On a live source time never goes
backwards, so the margin could be zero there.

### Gaps going forward

A forward seek, or the player dropping frames when it falls behind, leaves a
hole in the buffer. Timestamps still increase, so the backward check does not
catch it. If a hole matters to the analysis (an FFT, for instance), clear the
buffer when two consecutive frames are further apart than a few frame
intervals.

### A full window straight after a jump

With trimming alone, a jump beyond the margin leaves a partly full window that
refills as playback continues. If the analysis really needs a full window at
once, the module can read the history itself: set `reads_sources = True` and
read the missing span with `self.sources.consume(start, end)`, as
[range_summary/module.py](modules/range-summary/src/pswamp_modules/range_summary/module.py)
does. That read awaits, so the work moves into an async method, and the
module's worker needs the app's source settings (module cookbook, "A module
that reads the sources"). Use this only if a partial window is unacceptable.

## Example

```python
from collections import deque
from datetime import datetime, timedelta

from pswamp_core.modules import Module
from pswamp_models.pmu import PmuFrame

WINDOW = timedelta(seconds=10)    # what the analysis looks at
MARGIN = timedelta(seconds=5)     # how far back a step can go with a full window
MAX_GAP = timedelta(seconds=0.5)  # a larger gap between frames means a forward jump


class WindowedThingModule(Module):
    name = "windowed-thing"
    inputs = (PmuFrame,)
    outputs = (WindowedThingResult,)

    def __init__(self) -> None:
        super().__init__()
        self._header_id: str | None = None
        self._f: list[int] = []
        self._buf: deque[tuple[datetime, list[float | None]]] = deque()

    def process(self, frame: PmuFrame) -> WindowedThing | None:
        if frame.header.header_id != self._header_id:
            self._header_id = frame.header.header_id
            self._f = frame.header.columns(measurement="f")
            self._buf.clear()                                   # the columns changed
        now = frame.timestamp
        while self._buf and self._buf[-1][0] >= now:
            self._buf.pop()                                     # stepped or sought back
        if self._buf and now - self._buf[-1][0] > MAX_GAP:
            self._buf.clear()                                   # jumped forward
        self._buf.append((now, [frame.values[i] for i in self._f]))
        while now - self._buf[0][0] > WINDOW + MARGIN:
            self._buf.popleft()                                 # keep window + margin

        window = [row for t, row in self._buf if t >= now - WINDOW]
        if self._buf[0][0] > now - WINDOW:
            return None                                         # not a full window yet
        return ...  # analyse `window`
```

`WindowedThingResult` and its body stand for the module's own messages, which
live in `pswamp_models`. `uv run pswamp new module` writes them for you.

The module stays testable with no server: feed it frames in order with
`run_one` from a test or script, including an earlier frame to simulate a step
back, and the buffer behaves as it does in a running pipeline.
