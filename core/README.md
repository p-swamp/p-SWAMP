# pswamp-core

The shared pieces of the p-SWAMP server data architecture, over the messages
in `../models/` (`pswamp-models`): the transport between processes, the module contract, the sources
(`SourceModule`, `Playable`, the run's `ActiveSource` router), and pipelines. `doc/server-data-architecture.md` describes
how they fit together.

- Source: `src/pswamp_core/`
- Built on it: `../modules/<name>/` (one project per module or source); the
  pipeline files in `../pipelines/` are loaded by `pswamp_core.pipeline_config`.
  The core imports nothing from them.
- Tests: `tests/`, run by `uv run pswamp test server`
- Extra: `kafka` (the Kafka transport)
