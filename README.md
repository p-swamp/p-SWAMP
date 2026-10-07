# p-SWAMP (Power Stability Wide area Monitoring and Protection)

A platform for developing and testing WAMPAC applications, based on the research
project [NEWEPS](https://ri.diva-portal.org/smash/record.jsf?pid=diva2%3A1933825&dswid=2773).
The repository holds two implementations side by side:

| Path | What it is |
|---|---|
| [`desktop/`](desktop/) | The original single-process Python + Qt application, the `p-swamp` package. Its own README covers installation and the examples. |
| [`app/`](app/) | The client-server stack: a FastAPI server (`app/server-python/`) and a React web client (`app/client-web/`). |
| [`models/`](models/) | `pswamp-models`, every message of the server data architecture, one package per producer. |
| [`core/`](core/) | `pswamp-core`, the server data architecture: transport, modules, gateway, player, pipelines. |
| [`modules/`](modules/) | The analysis modules, one Python project each (`modules/<name>/`, `pswamp-<name>`). |
| [`legacy/pswamp-wiring/`](legacy/pswamp-wiring/) | Transitional: the pipelines and example data sources, until they become TOML and modules. |
| [`doc/`](doc/) | Documentation for the client-server stack. Start with [`doc/client-server-rig.md`](doc/client-server-rig.md). |

`models/`, `core/`, `modules/`, `tools/` and `app/server-python/` form one uv workspace with a single
`uv.lock` at the repository root (`uv sync` here). The desktop package keeps its
own lock in `desktop/`, so Qt never enters the server's resolution.

Contributors and coding agents: see [`AGENTS.md`](AGENTS.md).

**NOTE:** This code is being developed as part of ongoing research, and thus
contains experimental features. Use at your own risk!
