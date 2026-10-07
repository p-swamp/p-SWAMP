# Remote data integration contract

**Status:** preliminary. It is implemented by the `RemoteHistory` source
(the `remote-history` project) and the stub in this repo. Security, limits and schema governance are still open (see
"Not settled yet").

**This document is the contract.** It is written in terms of HTTP alone, so a
service can be built on any stack.

## Summary

p-SWAMP reads a deployment's historical PMU data through a small REST service
that the deployment runs in front of its own store. The service answers two
requests:

- **coverage**: what time range it holds;
- **query**: the records in a range, streamed back as the response body, one
  JSON line per record, closed by one terminal line.

The connection that asks is the one that answers. Closing it cancels the
query. p-SWAMP never sees the store, its schema or its location.

```text
p-SWAMP (RemoteHistory)                    deployment
   |  GET  /v1/coverage?model=pmu.frame        |
   |  POST /v1/queries                         |
   +------------------------------------------>| remote data service ──> any store
   |<------------------------------------------+
   |  200, NDJSON streamed as the store reads  |
```

In this repo:
- the client, a playable history source and a module project like any other
  (`pswamp-remote-history`, entry point `remote-history`):
  `modules/remote-history/src/pswamp_modules/remote_history/source.py`;
- the request and line models: `models/src/pswamp_models/remote_data/`;
- a stub service: `modules/remote-history/examples/remote_data_stub/`, serving
  the streamer's sample recording (any history source, by
  `REMOTE_DATA_STUB_SOURCE=name:entry-point`, `sample:sample-replay` by default).
  Run it with `modules/remote-history/examples` on the `PYTHONPATH`:
  `python -m remote_data_stub` (compose and k8s start it as `remote-data-stub`).

## Data

One model: `pmu.frame`, one instant of every channel in a stream, carrying its
channel layout (see "The record" below). Timestamps are ISO 8601 instants in
UTC (`Z`). Ranges are half-open: `[start, end)`.

## HTTP API

### Health

`GET /healthz` returns `200 {"status": "ok"}`.

### Coverage

`GET /v1/coverage?model=pmu.frame` returns:

```json
{"model": "pmu.frame", "start": "2026-01-01T00:00:00.05Z", "end": "2026-01-01T00:00:03.05Z"}
```

- `start` is the first record's timestamp.
- `end` is exclusive: where the next record after the last would be.
- `start: null` means the service holds nothing.
- An unknown model is `404`.

### Query a range

`POST /v1/queries`, `Content-Type: application/json`:

```json
{"version": "v1", "query_id": "9f1c…", "model": "pmu.frame",
 "start": "2026-01-01T00:00:01Z", "end": "2026-01-01T00:00:02Z"}
```

- `start` and `end` may be `null`, which means open.
- `query_id` is for matching the two sides' logs; it is not echoed.
- An unknown model is `404`, a malformed body `422`. Refuse whatever you can
  refuse *before* the first line: once the body starts, the status is sent.

## The streamed response

`200`, `Content-Type: application/x-ndjson`. One JSON object per line, UTF-8,
each line ending in `\n`:

| Line | Shape | When |
|---|---|---|
| record | `{"kind": "record", "model": "pmu.frame", "record": {…}}` | once per record, in ascending `timestamp` order, all inside `[start, end)` |
| end | `{"kind": "end", "count": 60}` | exactly once, last, when the query is complete |
| error | `{"kind": "error", "error": "…"}` | instead of `end`, when the query failed part way |

A body that stops without an `end` or `error` line is a broken connection, not
an empty answer, and the client fails the stream.

**Let the connection pace you.** Stream records as you read them, rather than
building the whole answer first. The client reads a line only when its player
wants the next frame, so a replay at real time holds the connection open for
the length of the range, and TCP backpressure paces your reads.

**Cancellation is closing the connection.** The client closes it on a seek,
or when the viewer leaves. Stop reading the store when the write fails. There
is no cancel route.

Set `X-Accel-Buffering: no` and `Cache-Control: no-cache`, so a proxy in
between does not buffer the stream into one blob.

## The record

`record` is a `pmu.frame` as JSON:

```json
{
  "version": "v1",
  "timestamp": "2026-01-01T00:00:01.05Z",
  "mRID": "n44-sample",
  "header": {
    "station": ["3000", "3000", "3000"],
    "channel": ["V", "V", "f"],
    "measurement": ["V_Magnitude", "V_Angle", "f"],
    "units": ["kV", "deg", "Hz"],
    "data_rate": 20.0
  },
  "values": [419.95, -0.0, 49.9999]
}
```

- `values` has one entry per header column; `null` where there is no value.
- `mRID` identifies the stream.
- The header rides in every record. Leave `cimReferenceId` out: p-SWAMP's
  source set sets it.
- The authoritative schema is `PmuFrame` in the api contract
  (`doc/api/openapi.json`, `components.schemas`).

## The client

A deployment names the source in its pipeline's source list, either in
`pipelines/<app>.toml` (`[[sources]] name = "remote"`, `module = "remote-history"`)
or, as compose and k8s do, through the environment; each source reads its own
`{NAME}_{SETTING}` variables, `REMOTE_*` for the source named `remote`:

```
PMU_TEST_STREAMER_SOURCES=sample:sample-replay,live:live-synthetic,remote:remote-history
REMOTE_URL=http://remote-data:8100      # required
REMOTE_TIMEOUT=30                       # seconds; default 30
```

- `REMOTE_TIMEOUT` bounds the wait for a response to start, and for each next
  line while the client is reading. A paused replay reads nothing and is not
  timed out.
- An unreachable service, a non-200 status, an `error` line and a missing
  `end` line all fail the stream. The player stops and shows the error, which
  also reaches the error tray.

## Checking a service

The conformance suite that every source passes (`pswamp_core.testing.SourceConformance`)
is the acceptance test.
Point `RemoteHistory` at your service and run it:

```python
class TestOurService(SourceConformance):
    @pytest.fixture
    def source_under_test(self):
        return RemoteHistory("remote", url="http://our-service:8100")   # name, then settings

    @pytest.fixture
    def conformance_records(self):
        return [...]    # what the service holds, in order
```

`modules/remote-history/tests/` does exactly this against the stub.

## Not settled yet

- Authentication and TLS between p-SWAMP and the service.
- Limits: the largest range per query, concurrent queries, rate.
- Models beyond `pmu.frame`, and how a schema change is versioned and agreed.
- Readiness of the store behind the service (`/healthz` is the process only).
