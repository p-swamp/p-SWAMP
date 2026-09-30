# pswamp-core

The shared pieces of the p-SWAMP server data architecture: the messages every
part exchanges, the transport between processes, the module contract, the data
gateway and player, and pipelines. `doc/server-data-architecture.md` describes
how they fit together.

- Source: `src/pswamp_core/`
- Tests: `tests/`, run by `scripts/run-python-server-tests.sh`
- Extras: `kafka` (the Kafka transport), `remote-data` (the remote data client)
