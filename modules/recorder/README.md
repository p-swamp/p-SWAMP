# recorder

`pswamp-recorder`, package `pswamp_modules.recorder`, class `Recorder`,
entry point `recorder` (group `pswamp.modules`).

Records the `PmuFrame`s of a live source to disk, and plays them back as a
history source: paced, seekable, with the player's usual controls. One class,
`Recorder(Playable, SourceModule)`: a source that also has an input.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | `PmuFrame`, from the live source named by `FEED` | `pmu.frame` | `pswamp_models.pmu` |
| Emits | `PmuFrame` (what it holds, when played back) | `pmu.frame` | `pswamp_models.pmu` |

## How it records

The shared run of the live source named by `FEED` hands the recorder every
frame it publishes (`PipelineRun._tapes` in `pswamp_core.pipeline`); a client's
run never does. The recorder keeps them under `DIR/<source name>/` as DuckDB
files, one per **segment**:

- a segment holds frames of one layout (`PmuHeader.header_id`); a new layout,
  a restart of the stream (`reset`), or `ROLL_HOURS` of frames starts a new one;
- `pmu(ts, mRID, layout, vals DOUBLE[])` holds the frames, `layouts` each header once;
- frames are buffered and written every `FLUSH_SECONDS`, and on `teardown`;
  a crash loses at most that much;
- over `MAX_BYTES` the oldest closed segment is deleted, never the open one.

A connection is opened per write and per read, so a reader never meets a
writer's open file. `coverage` and `read` span every segment, in time order.

**Settings** (`{SOURCE}_{SETTING}`, `RECORDED_DIR` for a source named `recorded`):

| Setting | Meaning | Default |
|---|---|---|
| `DIR` | The folder recordings are kept in (required) | |
| `FEED` | The live source it records; unset, it only plays back | |
| `ROLL_HOURS` | Hours of frames after which a new segment starts | 6 |
| `FLUSH_SECONDS` | Seconds between writes to disk | 1 |
| `MAX_BYTES` | Bytes kept | 5 GiB |

## In a pipeline

It is opt-in, because it needs a place to write. Name it like any source, in
`PMU_TEST_STREAMER_SOURCES` (`recorded:recorder`), with its settings.
`docker-compose.recording.yml` does that, and mounts the volume (ADR-018):

    docker compose -f docker-compose.yml -f docker-compose.recording.yml up --build

It is not in `pipelines/pmu-test-streamer.toml`: `DIR` is required, so every
default run would fail without it.

## From a script

    uv run python modules/recorder/examples/record_and_replay.py [folder]

`run(frame)` records, `flush()` writes, `read(start, end)` plays back a
half-open range: no server, no event loop.

## Not in v1

Other models (`ScadaScan`, `SimEvent`), a recordings page, an age limit.

## Grids

A frame keeps the `cimReferenceId` it was recorded under (enrichment never
overwrites one). When a run plays a recording made under another grid than its
own, `Playable` reports it once on the error tray and plays on. A new grid in
the middle of a recording starts a new segment.

## Tests

`uv run pswamp test module recorder` (also part of `uv run pswamp test server`).
It passes `pswamp_core.testing.SourceConformance`. The hook in the core is
tested in `core/tests/test_pipeline_recording.py`, and the whole path with the
real live source in `app/server-python/tests/test_recorder_pipeline.py`.
