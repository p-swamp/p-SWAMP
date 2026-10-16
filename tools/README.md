# pswamp-tools

The `pswamp` command line: the repo's automation as one Typer CLI that runs
natively on Windows, macOS and Linux. It replaced a folder of bash scripts, some
of which embedded Python in heredocs and none of which ran on Windows.

    uv run pswamp --help

**The help text of every command and group is the documentation** (`uv run pswamp
<group> --help`); this file is only the map.

| Command | What it does |
|---|---|
| `pswamp check` | The static gate before every push, and what CI runs: lockfile, syntax, ruff `--select F`, `tsc`, eslint, the pipeline files, the api contract. Runs every check, exits non-zero on any failure. |
| `pswamp api generate [--check]` | Regenerate (or verify) `doc/api/openapi.json` and `app/client-web/src/api/schema.ts`. |
| `pswamp test server\|module <name>\|desktop\|smoke\|playwright` | The test suites. `server` is the fast hermetic one CI gates on; `smoke` and `playwright` start the real container. |
| `pswamp modules list` | Every installed module and source: kind, what it reads and emits, the commands it takes. |
| `pswamp pipelines validate [files]` | Load each `pipelines/*.toml` as the server and the workers do, and run every check. |
| `pswamp new subapp <slug> <label>` | A page and its api (a per-client counter). |
| `pswamp new module <slug> <label> [--source [--playable]]` | A module project and its page, or a data source project. |
| `pswamp check-generators` | Prove both generators still produce working apps, in a throwaway worktree. |
| `pswamp dev server\|client` | The hot-reloaded local dev loop. |
| `pswamp deploy minikube\|logs` | Build into a local minikube cluster and deploy `k8s/p-swamp-local.yaml`; follow its logs. |
| `pswamp deps update` | Pull every dependency forward and report what moved. |

Behaviour worth knowing:

- **A missing tool is a one-line error with an install hint** (uv, node/npm/npx,
  docker or podman, git, minikube, kubectl), never a traceback.
- **docker or podman**: the container engine is detected, including podman behind
  a `docker` alias, and the compose command that actually answers is used.
- **It never runs bare `python`** (on Windows that can be the Microsoft Store
  stub); Python tools run through `uv run`.

Layout: `src/pswamp_tools/main.py` registers the commands in
`src/pswamp_tools/commands/`; helpers shared by them are `_paths.py` (repo root
discovery), `_proc.py` (running tools), `_docker.py` (engine detection), `_ui.py`
(rich output) and `_net.py`. The generators are `generate.py` plus
`src/pswamp_tools/templates/` (see its [README](src/pswamp_tools/templates/README.md)).
Tests are `tests/test_tools_*.py`, and run with the server's through
`pswamp test server`; `tests/test_tools_layering.py` enforces the module projects'
rules (what they may import, what a module folder may hold).
