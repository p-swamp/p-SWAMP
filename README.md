# p-SWAMP (Power Stability Wide area Monitoring and Protection)

A platform for developing and testing WAMPAC applications, based on the research
project [NEWEPS](https://ri.diva-portal.org/smash/record.jsf?pid=diva2%3A1933825&dswid=2773).
The repository holds two implementations side by side:

| Path | What it is |
|---|---|
| [`desktop/`](desktop/) | The original single-process Python + Qt application, the `p-swamp` package. Its own README covers installation and the examples. |
| [`app/`](app/) | The client-server stack: a FastAPI server (`app/server-python/`) and a React web client (`app/client-web/`). |
| [`models/`](models/) | `pswamp-models`: every message of the server data architecture, one package per producer. |
| [`core/`](core/) | `pswamp-core`: transport, the module and source contracts, the run's router, pipelines. |
| [`modules/`](modules/) | The analysis modules and the data sources, one Python project each (`modules/<name>/`). See its [index](modules/README.md). |
| [`pipelines/`](pipelines/) | One pipeline file per app (`<app>.toml`): its modules, its sources, its enrichment. |
| [`tools/`](tools/) | The `pswamp` command line, which is all of the repo's automation. |
| [`doc/`](doc/) | Documentation for the client-server stack. Start with [`doc/client-server-rig.md`](doc/client-server-rig.md); decisions are in [`doc/adr/`](doc/adr/). |

`models/`, `core/`, `modules/*`, `tools/` and `app/server-python/` form one
[uv](https://docs.astral.sh/uv/) workspace with a single `uv.lock` at the repository
root. The desktop package keeps its own lock in `desktop/`, so Qt never enters
the server's resolution.

## Quickstart

You need [uv](https://docs.astral.sh/uv/), plus Node.js for the web client and
docker or podman for the container. On Windows, macOS and Linux alike:

```
uv sync                       # every workspace member, into ./.venv
uv run pswamp --help          # the CLI: every command and group has --help
uv run pswamp check           # the static checks, what CI runs
uv run pswamp test server     # the unit tests of the server, models, core, modules and tools
uv run pswamp dev server      # the server on 127.0.0.1:8000 (in one terminal)
uv run pswamp dev client      # the web client with hot reload on http://localhost:5173 (in another)
```

A module is plain Python and runs from a script, with no server: this replays the
sample recording through the frame statistics module and plots it
(`modules/sample-replay/examples/replay_stats.py`):

```python
from pswamp_modules.frame_stats import FrameStatsModule
from pswamp_modules.sample_replay import SampleReplay

stats = FrameStatsModule()
results = [stats.run_one(frame).result for frame in SampleReplay().read()]
```

```
uv run --package pswamp-sample-replay --extra examples python modules/sample-replay/examples/replay_stats.py
```

To add to it: `uv run pswamp new module <slug> "<Label>"` (an analysis module and its
page), `... --source` (a data source), or `uv run pswamp new subapp <slug> "<Label>"`
(a page and its api). [`doc/module-cookbook.md`](doc/module-cookbook.md) is the recipe.

Contributors and coding agents: see [`AGENTS.md`](AGENTS.md).

**NOTE:** This code is being developed as part of ongoing research, and thus
contains experimental features. Use at your own risk!
