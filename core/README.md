# pswamp-core

The shared pieces of the p-SWAMP server data architecture, over the messages
in `../models/` (`pswamp-models`): the transport between processes, the module contract, the data
gateway and player, and pipelines. `doc/server-data-architecture.md` describes
how they fit together.

- Source: `src/pswamp_core/`
- Built on it: `../modules/<name>/` (one project per module) and the
  transitional `../legacy/pswamp-wiring/` (pipelines and example sources).
  The core imports nothing from either.
- Tests: `tests/`, run by `uv run pswamp test server`
- Extras: `kafka` (the Kafka transport), `remote-data` (the remote data client)
