# Python API

Generated from the docstrings in the source. For how the pieces fit together,
read [the server data architecture](../../server-data-architecture.md) first;
for a recipe, [the module cookbook](../../module-cookbook.md).

Three kinds of package make up the server side:

| Package | Distribution | What it holds |
|---|---|---|
| `pswamp_core` | `pswamp-core` | The contract every module implements, the sources, pipelines, the transport between modules, and the CIM grid model. |
| `pswamp_models` | `pswamp-models` | Every message that crosses the transport or a socket, one package per producer. |
| `pswamp_modules.<name>` | `pswamp-<name>` | One package per module. Each is documented in its own section of the [Modules](../../modules/index.md) tab, with an API page beside its overview. |

## The core

| Page | What is on it |
|---|---|
| [Modules](core-modules.md) | `Module`, the three input styles and joins, keeping up with a stream. |
| [Sources](core-sources.md) | `SourceModule`, `Playable`, the source set and its `ActiveSource` router, time ranges. |
| [Pipelines](core-pipelines.md) | Pipeline files, runs, hosts and workers, relays and enrichment. |
| [Transport](core-transport.md) | The pub/sub transport between modules (in memory or Kafka) and command routing. |
| [The CIM graph](core-cim.md) | The grid model every module can read: the store, the version stamp, measurements, limits. |
| [Scripts and testing](core-scripts-testing.md) | Running a module from a script, settings, logging, and the conformance helpers for tests. |

## The messages

One page per producer package of `pswamp_models`, listed under *Messages* in
the navigation.
