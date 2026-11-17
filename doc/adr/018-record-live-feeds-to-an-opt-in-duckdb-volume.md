# ADR-018: Record a live feed into an opt-in DuckDB volume, played back as a source

- Status: Accepted
- Date: 2026-11-10

## Context

A live source exists only in the present: a viewer who missed a disturbance
cannot see it again, and the only way back is to run the simulation again. The
stack keeps nothing on purpose (ADR-012: p-SWAMP stores nothing; a deployment's
history sits behind a remote data contract), and AGENTS.md forbids a volume
without an explicit ask. The ask is now made: record the live feed, and play it
back with the player the stack already has.

## Decision

We will add a `recorder` module (`modules/recorder/`): one class,
`Recorder(Playable, SourceModule)`, that records the `PmuFrame`s of a named live
source and is, at the same time, a playable history source over what it holds.

- **Fed by the live run, not the transport.** A history source may declare
  `inputs` and a `FEED` setting; the shared run of that live source hands it every frame it
  publishes (`PipelineRun`, `pswamp_core.pipeline`), in order, and calls `reset` when the
  stream starts over and `teardown` when the run stops. A client's run never feeds it.
  `Pipeline` still refuses a source listed among its modules (ADR-006): it stays a source,
  read by the router of a run, and the shared run's instance is another instance of the
  class than the ones clients play back, the two sharing only the folder.
- **DuckDB files, one per segment**, under `DIR/<source>/`: a new segment for each
  layout, restart of the stream, or `ROLL_HOURS`; PMU values as `DOUBLE[]`, each header
  stored once. A connection is opened per write and per read.
- **Retention by size** (`MAX_BYTES`): the oldest closed segment goes first.
- **Opt-in.** `DIR` is a required setting, so the recorder is named in
  `<APP>_SOURCES` by a deployment that wants it, not in `pipelines/*.toml`.
  `docker-compose.recording.yml` adds it with a named volume; `k8s/base` stays
  volume-free, and a deployment's overlay adds a claim.

## Consequences

- The stack can now hold state across a restart, but only when asked to, and
  only recordings: nothing else gains persistence, and the volume can be deleted
  at any time without breaking anything.
- A recording is the stream as the run published it, enriched: its frames carry
  the `cimReferenceId` and Analog mRIDs of the grid at that time, and enrichment
  leaves a reference a frame already has, so a replay keeps them. `Playable`
  compares each id it meets with the run's own (its enricher's `reference`) and
  puts one `ErrorEvent` on the tray per other grid; playback goes on. A change of
  grid in the middle of a recording starts a new segment.
- What is recorded is chosen per recorder (`MESSAGES`, default `PmuFrame`) among
  the messages whose class says `recordable = True` (`pswamp_models.common.recordable_models()`):
  a producer opts its message in, and nothing is listed elsewhere. Every
  recordable message has a typed table of its own, derived from its pydantic
  model (`t_<topic>`: `ts`, `arrived`, a column per field, DuckDB `STRUCT`/list
  types, `JSON` for the rest); `PmuFrame` keeps its tailored `pmu` + `layouts`
  tables behind the same codec interface. A segment's `meta` table keeps each
  topic's version and column signature, so an older segment is read by the model
  as it is now, skipping rows that no longer validate. `read_messages(start, end,
  topics)` returns them merged by `ts`; the player's `read` is still frames only.
- A message reaches the recorder from the live source's shared run (what it
  publishes) or, for a module's output (results, alarms), from a transport
  subscription under the run's key, so a module in a worker is recorded too.
  The two arrive in the order the run saw them, not by message time; `arrived`
  and `ts` are both kept.
- A crash loses up to `FLUSH_SECONDS` of frames; a shutdown loses none.
- The core gains a small, specific hook; a history source with `inputs` is a new
  kind of thing that only the shared run of a live source feeds.
- Retention has no age bound: a feed that goes quiet keeps its data until the
  bytes run out.

## Alternatives considered

- **A recorder as a hosted `Module`, with a second class to play back**: a
  `ModuleHost` builds one instance per run key, so it would record every
  client's replay too.
- **Subscribing to the transport's `live.<source>` topics**: the shared run
  already sees each frame, in order, in its own process; the transport would add
  a JSON round trip per frame for nothing.
- **Parquet files, or SQLite**: no engine, or a familiar one, but neither gives
  cheap range reads of wide numeric rows; DuckDB does, embedded.
- **A time-series database service**: a service, a volume and a deployment
  burden for what is one folder of files.
- **Recording in the remote data service (ADR-012)**: that service is the
  deployment's own history; the recorder is for what a run just showed.
