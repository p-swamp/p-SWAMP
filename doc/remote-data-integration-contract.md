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
- **query**: the records in a range, at most `limit` of them, streamed back
  as the response body, one JSON line per record, closed by one terminal line.

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
- a stub service: `modules/remote-history/examples/remote_data_stub/`, generating
  two synthetic stations at 50 Hz over a history source's coverage (selected by
  `REMOTE_DATA_STUB_SOURCE=name:entry-point`, `sample:sample-replay` by default).
  Run it with `modules/remote-history/examples` on the `PYTHONPATH`:
  `python -m remote_data_stub` (compose and k8s start it as `remote-data-stub`).

## Data

One model: `pmu.frame`, one instant of every channel in a stream, carrying its
channel layout (see "The record" below). Timestamps are ISO 8601 instants in
UTC (`Z`). Ranges are half-open: `[start, end)`.

## HTTP API

### Health

`GET /health/live` returns `200 {"status": "ok"}`.
`GET /health/ready` returns `200 {"status": "ok"}`.

### Coverage

`GET /v1/coverage`, `x-request-id: 9f1c….1` returns:

```json
{
  "start": "2026-01-01T00:00:00.05Z",
  "end": "2026-01-01T00:00:03.05Z",
  "stations": [
    {"id": "NO 12345", "name": "NO 12345 stasjon AB3"},
    {"id": "NO 54321", "name": "NO 54321 stasjon BA1"}
  ]
}
```

- `start` is the first record's timestamp.
- `end` is exclusive: where the next record after the last would be.
- `start: null` means the service holds nothing.
- `stations` is the full list of available stations, it is not guarantied that each station starts and ends at `start`/`end`.

### Query a range

`POST /v1/queries`, `Content-Type: application/json`, `x-request-id: 9f1c….1`:

```json
{
  "version": "v1",
  "stations": ["NO 12345", "NO 54321"],
  "start": "2026-01-01T00:00:01Z",
  "end": "2026-01-01T00:00:02Z",
  "limit": 30000
}
```

- `stations` filters by station ID; omitted or null means all stations.
  An empty list is rejected with HTTP 422, since it is likely unintentional.
- `start` and `end` are ISO timestamps; null means the corresponding coverage bound.
- `limit` is the target number of station records per page. Complete the final
  timestamp even when this exceeds the limit, so no station is lost on the next page.
- `x-request-id` optional header is used to match request_id in logs between client and server. Is automatically generated on server if omitted.

### Pages

The client reads a long range as pages. It asks for `limit` records from
`start`; when a page holds `limit` of them, it asks again from one
microsecond after the last one's timestamp, until a page comes back short or
the range ends. Each page is its own query, with its own `x-request-id` header
(`<id>.<n>`).

- A page is bounded by records, not by time, so a gap of weeks costs one
  query and a range of months is many small ones.
- Records are ordered by timestamp then station. All records of one timestamp
  must stay in the same page. The backend groups consecutive equal `msg.ts`
  values into one `PmuFrame`, emitting the group when the next timestamp arrives
  or an `end` line completes the stream. The sampling interval is 20 ms (50 Hz).
- A malformed body is `422`. Refuse whatever you can
  refuse *before* the first line: once the body starts, the status is sent.

## The streamed response

`200`, `Content-Type: application/x-ndjson`. One JSON object per line, UTF-8,
each line ending in `\n`:

| Line | Shape | When |
|---|---|---|
| record | `{"kind": "record", "msg": {...}}` | once per station and timestamp, ordered by `msg.ts` then station, inside `[start, end)` |
| end | `{"kind": "end", "msg": {"count": 60}}` | exactly once, last, when the query is complete |
| error | `{"kind": "error", "msg": {"message": "..."}}` | instead of `end`, when the query failed part way |

A body that stops without an `end` or `error` line is a broken connection, not
an empty answer, and the client fails the stream.

**Let the connection pace you.** Stream records as you read them, rather than
building the whole answer first. The client reads a line only when its player
wants the next frame, so a replay at real time holds the connection open for
the length of the page, and TCP backpressure paces your reads.

**Cancellation is closing the connection.** The client closes it on a seek,
or when the viewer leaves. Stop reading the store when the write fails. There
is no cancel route.

Set `X-Accel-Buffering: no` and `Cache-Control: no-cache`, so a proxy in
between does not buffer the stream into one blob.

## The record

`record` format `raw` is a `pmu.frame` as JSON as they come from the database:

```json
{
  "mRID": "9f1c….1",
  "v"   : "v1",
  "ts"  : "2026-11-03T00:00:01.05Z",
  "seq" : 1,
  "kind": "record",
  "msg" : {
    "ts"       : "2026-01-01T00:00:01.05Z",
    "id"       : "NO 12345",
    "name"     : "NO 12345 stasjon AB3",
    "frequency": 50.0,
    "rocof"    : 0.01,
    "phasors"  : [
      {"name": "420_da2_U_L1", "station": "da2", "kv": 420, "kind": "U", "phase": "L1", "bank": null, "magnitude": 226382.95, "angle": -85.67},
      {"name": "420_da2_U_L2", "station": "da2", "kv": 420, "kind": "U", "phase": "L2", "bank": null, "magnitude": 226382.95, "angle":  34.33},
      {"name": "420_da2_U_L3", "station": "da2", "kv": 420, "kind": "U", "phase": "L3", "bank": null, "magnitude": 226382.95, "angle": 154.33},
      {"name": "420_da2_I_L1", "station": "da2", "kv": 420, "kind": "I", "phase": "L1", "bank": null, "magnitude":      0.94, "angle": -85.67},
      {"name": "420_da2_I_L2", "station": "da2", "kv": 420, "kind": "I", "phase": "L2", "bank": null, "magnitude":      0.94, "angle":  34.33},
      {"name": "420_da2_I_L3", "station": "da2", "kv": 420, "kind": "I", "phase": "L3", "bank": null, "magnitude":      0.94, "angle": 154.33}
    ]
  }
}
```

- `mRID` identifies the stream, taken from `x-request-id`.
- `ts` is the time response chunk was created
- `seq` is the chunk number
- `kind` is the type of the `msg` record.
- `msg.ts` timestamp of the record.
- `msg.id` station ID, matching the IDs in coverage and the `stations` query filter.
- `msg.name` station name.
- `msg.frequency` station frequency.
- `msg.rocof` station rate of change of frequency.
- `msg.phasors.x.name` name of phasor, specifies expected voltage, other station, voltage or ampere, and phase.
- `msg.phasors.x.magnitude` voltage or amps
- `msg.phasors.x.angle` voltage or amp phase angle
- The remote schema is `RecordResponse` in `pswamp_models.remote_data`;
  it is not the downstream `PmuFrame` schema. The backend builds one frame per
  timestamp, labels columns by station ID, maps frequency/ROCOF to `f`/`df`,
  converts voltage magnitudes from V to kV, and keeps current in A and angles
  in degrees. Its stable stream ID is the configured source instance name.

## The client

A deployment names the source in its pipeline's source list, either in
`pipelines/<app>.toml` (`[[sources]] name = "remote"`, `module = "remote-history"`)
or, as compose and k8s do, through the environment; each source reads its own
`{NAME}_{SETTING}` variables, `REMOTE_*` for the source named `remote`:

```
PMU_TEST_STREAMER_SOURCES=sample:sample-replay,live:live-synthetic,remote:remote-history
REMOTE_URL=http://remote-data:8100      # required
REMOTE_TIMEOUT=30                       # seconds; default 30
REMOTE_COVERAGE_TIMEOUT=10              # seconds; default 10
REMOTE_PAGE=30000                       # records per query; default 30000
```

- `REMOTE_TIMEOUT` bounds the wait for a response to start, and for each next
  line while the client is reading. A paused replay reads nothing and is not
  timed out.
- `REMOTE_PAGE` is each query's `limit`: 30000 is ten minutes at 50 Hz.
- `REMOTE_COVERAGE_TIMEOUT` bounds `GET /v1/coverage`, which a seek and a
  switch to the source wait on. A switch away from a source that hangs does
  not wait: it stops the command in progress.
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
- Limits: concurrent queries, rate. (The size of a query is `limit`.)
- Models beyond `pmu.frame`, and how a schema change is versioned and agreed.
- Readiness of the store behind the service (`/healthz` is the process only).
