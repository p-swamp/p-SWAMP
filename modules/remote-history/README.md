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

`coverage` is `GET /v1/coverage?model=pmu.frame`; `read` is `POST /v1/queries`,
whose NDJSON answer is read a line at a time, so closing the stream early (a
seek) closes the connection, which is the service's cue to stop. A paused replay
reads nothing and is not timed out.

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

An `httpx` client is made per call and closed at its end, so the source holds
no connection between reads.

## Examples

`examples/read_remote.py` reads a range from a service given by `--url`, defaulting to
`REMOTE_URL`:

    uv run python modules/remote-history/examples/read_remote.py --url http://127.0.0.1:8100

The remote data stub (`core/examples/remote_data_stub/`, `python -m remote_data_stub`) is
a service to try it against.

## Tests

`uv run pswamp test module remote-history` (also part of `uv run pswamp test server`).
