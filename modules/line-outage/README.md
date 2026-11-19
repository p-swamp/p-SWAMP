# line-outage

`pswamp-line-outage`, package `pswamp_modules.line_outage`, class `LineOutageModule`,
entry point `line-outage` (group `pswamp.modules`).

The Line outage module: the desktop package's `LineOutageDetectionApp`
(`pswamp.monitoring.line_outage_detection`) as a module. It keeps the last `window_s`
seconds of every current magnitude column of the stream (measurement `I_Magnitude`, or the
recordings' `i_Magnitude`; `A` or `kA`), and `eval_freq` times a second of message time
looks at them: a current below `threshold_a` amperes over the whole window carries none.

Every evaluation is published. It lists what changed since the last one (`changes`: a
`disconnect` or a `connect`, with the currents concerned) and every current carrying none now
(`disconnected`), each with its station, channel and, when the stream says, the CIM Analog it
measures (`PmuHeader.analog`). Its `status` is `Alert` while any current carries none, `OK`
otherwise.

| | Message | Defined in |
|---|---|---|
| Reads | `PmuFrame` | `pswamp_models.pmu` |
| Emits | `LineOutageResult` (body `LineOutageBody`) | `pswamp_models.line_outage` |
| Accepts | no command | |

**Parameters:** `window_s` (0.2 s), `eval_freq` (5 per second), `threshold_a` (1 A), all
constructor arguments. Nothing is published until the window has filled. A current with no value
over the whole window (a branch the stream does not have) keeps its state. At the start, and after
`reset`, every current is taken to carry some, so a branch already out is a `disconnect` at the
first evaluation; a frame with a new layout starts over the same way.

The live grid simulation (`rtsim-from-cim`) measures the currents of lines, not of
transformers, so a transformer is never reported.

## From a script

No server, transport or event loop: `process` is plain synchronous code.

```python
from pswamp_modules.line_outage import LineOutageModule

module = LineOutageModule()
for frame in frames:
    for result in module.run(frame):       # 5 times a second
        result.result.changes              # [] unless something changed
        result.result.disconnected         # every current carrying none
```

## Examples

`examples/run_line_outage.py` runs the module over a synthetic line trip:

    uv run python modules/line-outage/examples/run_line_outage.py

## Tests

`uv run pswamp test module line-outage` (also part of `uv run pswamp test server`).
