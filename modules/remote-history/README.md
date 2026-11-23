# remote-history

`pswamp-remote-history`, package `pswamp_modules.remote_history`, class
`RemoteHistory`, entry point `remote-history` (group `pswamp.modules`).

A **source**: it has no inputs, it produces. A *history* served by a remote data
service: the deployment runs a small REST service in front of whatever store
holds its history, and this source speaks the contract
(`doc/remote-data-integration-contract.md`) and knows nothing of the store. It
is *playable*: the player controls apply, with the connection as the pacing.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | nothing | | |
| Emits | `PmuFrame` (the primary, paced stream) | `pmu.frame` | `pswamp_models.pmu` |
| Accepts | `PlayCommand`, `PauseCommand`, `StepCommand`, `SeekCommand`, `SpeedCommand` | | `pswamp_models.player` |

**Settings** (a deployment sets `{SOURCE}_{SETTING}`, `REMOTE_URL` for a source
named `remote`; a script passes keywords):

| Setting | | |
|---|---|---|
| `url` | required | Base URL of the service, `http://remote-data:8100` |
| `timeout` | `30` | Seconds to wait for an answer to start, and for each line |
| `coverage_timeout` | `10` | Seconds to wait for the coverage, which a seek and a switch to this source wait on |
| `page` | `30000` | Records per query; a full page is followed by the next |
| `gap` | `1` | Seconds without frames that the player crosses at once and reports (every playable source has it) |

`coverage` is `GET /v1/coverage` and returns a `TimeRange` (or `None`);
`read` is `POST /v1/queries`, whose NDJSON answer is read a line
at a time, so closing the stream early (a seek) closes the connection, which is
the service's cue to stop. Each record describes one station at one timestamp,
ordered by timestamp then station. Consecutive records with equal `msg.ts` are
combined into one `PmuFrame`; the last group is emitted on the terminal `end`
line. Frames use a 20 ms interval (50 Hz) and station IDs as labels. Each station
contributes six columns, computed here from its record; the individual phasors
are not passed on:

| Measurement | Unit | From |
|---|---|---|
| `f`, `df` | Hz, Hz/s | the record's `frequency` and `rocof` |
| `P`, `Q` | MW, Mvar | what passes the station: for each feeder (the current phasors of one station, level and bank whose names differ only by phase), `P = V·I·cos(a)` and `Q = V·I·sin(a)` with the voltage of the same station, level and phase and `a` the voltage angle minus the current angle, summed over the phases. The station's value is the larger of the feeders' positive and negative sums, so the direction the current is counted in does not matter. Voltage is phase to neutral. Empty without a feeder |
| `v_dev` | % | the voltage magnitude furthest from the nominal `kv/√3` of its level, signed |
| `VUF` | % | voltage unbalance factor: negative-sequence over positive-sequence voltage; the worst of the levels with all three phases |

The sequences assume the usual rotation: L2 lags L1 by 120°, L3 leads it by 120°.
A phasor with magnitude 0 is taken as missing and left out of every column.

A page includes every station at its final timestamp, even if this exceeds
`page`. A full page is followed by a query from one
microsecond after its last record, so a gap of weeks costs one query. A paused
replay reads nothing and is not timed out.

## From a script

The source is written as async code (the data is remote); the synchronous
`read` and `coverage` drive it on a private event loop, so no `asyncio` in your
code. Inside a running loop (a notebook), use `aread` and `acoverage`.

```python
from pswamp_modules.remote_history import RemoteHistory

source = RemoteHistory(url="http://remote-data:8100")
print(source.coverage())
frames = list(source.read(start, end))
```

An `httpx` client is made per call (one `read`, all its pages) and closed at
its end, so the source holds no connection between reads.

## Examples

`examples/read_remote.py` reads a range from a service given by `--url`, defaulting to
`REMOTE_URL`:

    uv run python modules/remote-history/examples/read_remote.py --url http://127.0.0.1:8100

The remote data stub (`examples/remote_data_stub/`, `python -m remote_data_stub` with
`examples/` on the `PYTHONPATH`) is a service to try it against: it generates two
synthetic stations at 50 Hz over the coverage of a history source,
`sample-replay` by default (`REMOTE_DATA_STUB_SOURCE=name:entry-point`).
Compose and k8s run it with `history:synthetic-history`: a year with outages, as
a long-term store would hold.

## Tests

`uv run pswamp test module remote-history` (also part of `uv run pswamp test server`).
