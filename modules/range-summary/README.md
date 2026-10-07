# range-summary

`pswamp-range-summary`, package `pswamp_modules.range_summary`, class
`RangeSummaryModule`, entry point `range-summary` (group `pswamp.modules`).

A batch query: asked about `[offset_s, end_offset_s)` of a recording, it reads
that range from its own data gateway and answers with the frame count and the
min, max and mean frequency over it.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | no topic (`inputs = ()`); it reads its gateway (`reads_gateway = True`) | | |
| Emits | `RangeSummaryResult` (body `RangeSummary`), carrying the command's `request_id` | `range.summary.result` | `pswamp_models.range_summary` |
| Accepts | `SummarizeRangeCommand(source, offset_s, end_offset_s)` | `summarize.range` | `pswamp_models.range_summary` |

**Parameters:** none. A command is refused (`CommandRefused`, which the host
publishes as an `ErrorEvent`) when the source is unknown, is live rather than
history, the range is empty, or the range holds no frame. Reading the gateway
awaits, so the module answers in `ahandle`; hosted, it can run in a worker of
its own (`batch-worker` in `docker-compose.yml`).

## From a script

The module needs a gateway, set by its host or by hand. `run_command` runs the
async handler on a loop of its own, so the script stays synchronous.

```python
from pswamp_models.range_summary import SummarizeRangeCommand
from pswamp_modules.range_summary import RangeSummaryModule

summary = RangeSummaryModule()
summary.gateway = gateway                  # a pswamp_core DataGateway with a history source
(answer,) = summary.run_command(SummarizeRangeCommand(source="sample", offset_s=0, end_offset_s=1))
answer.result.mean_frequency_hz
```

## Examples

`examples/summarize_range.py` gives the module a gateway over a small synthetic
recording (a minimal in-memory `DataClient`) and summarizes four ranges of it:

    uv run python modules/range-summary/examples/summarize_range.py

## Tests

`uv run pswamp test module range-summary` (also part of `uv run pswamp test server`).
