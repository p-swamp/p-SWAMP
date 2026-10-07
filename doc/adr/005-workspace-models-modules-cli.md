# ADR-005: One uv workspace of models, module projects and a CLI

- Status: Accepted
- Date: 2026-10-07

## Context

The client-server stack had grown four loosely connected Python projects (the
desktop package at the repo root, `core/`, `modules/`, the server) with two
lockfiles, and three problems followed:

- **Messages were spread over three places**: the core, each module's
  `module.py`, and the server. To read a module's result type you imported the
  module.
- **`modules/` was one project mixing three kinds of code**: analysis modules,
  pipeline declarations, and data sources. A contributor could not understand,
  test or ship one module on its own.
- **Automation was 13 bash scripts**, several embedding Python in heredocs, none
  of which ran on Windows, where much of the team works.

A module was also hard to use outside the server: `process` was async and tied
to the host, so a researcher with a notebook or a plain script, who is the other
audience for this code, had to stand up a transport to call an analysis.

[ADR-004](004-use-a-monorepo.md) settled that this stays one repository. This
records how it is organised inside it. The wire (topics, JSON shapes,
`doc/api/openapi.json`) was to stay identical throughout.

## Decision

- **One uv workspace, one lockfile; the desktop package stays outside it.**
  `models/`, `core/`, `modules/*`, `tools/` and `app/server-python/` are members
  of the workspace rooted at the repo root. The desktop Qt package moves to
  `desktop/` with its own lock, so PySide6 and Kafka never enter the server's
  resolution; the server reaches it through one editable path dependency.
- **One models package, a folder per producer.** `pswamp-models`
  (`pswamp_models`) holds every message, depends on pydantic only, and every
  consumer imports from it: the core, other modules, the server and the api
  contract. Nobody imports a module to get at its data, and a message class is
  still its topic name, so nothing on the wire changes.
- **One project per module, found by entry point.** `modules/<name>/` holds
  code, tests, README, examples and nothing else, in the `pswamp_modules` PEP 420
  namespace, and registers itself in the `pswamp.modules` entry-point group. It
  depends on `pswamp-core` and `pswamp-models` only. A layering test enforces
  this for every module, so a new one is covered with no edit.
- **A synchronous module API with a join.** A module declares `inputs` and
  `outputs` (several of each) and writes a synchronous `process`. Three input
  styles share one base class: one input, independent inputs with `@on`
  handlers, and named simultaneous inputs combined by a `Latest` join whose age
  check uses message timestamps, so a replay behaves like the live feed.
  `run`/`run_one` call a module from a script and return what a host would
  publish; `arun` is what the host calls, in a thread if `blocking`. A command a
  module sends is a declared output; there is no `emit()`.
- **Sources are modules, run in-process, with a `Playable` mixin.**
  `SourceModule` (no inputs, `read`/`aread`, `coverage`) is the contract for
  sample replay, live and remote history; a history that mixes in `Playable`
  carries the pacing and the player commands. A run holds its sources in a
  `SourceSet` and an `ActiveSource` router that switches the active one and
  routes the player commands to it. The router reads sources directly, in the
  process that owns the run.
- **Pipelines are TOML, one file per app.** `pipelines/<app>.toml` names modules
  and sources by entry point. `Pipeline.load` keeps the existing checks (one
  receiver per command, one class per topic) and adds one: every class a module
  reads has a producer. Environment variables still override the file
  (`<APP>_SOURCES`), so sources stay configured, not coded.
- **One Typer CLI replaces the bash scripts.** `pswamp` (`tools/`), run as
  `uv run pswamp …`, works natively on Windows, detects docker or podman, names
  a missing tool with an install hint, and has `--help` on every command as the
  documentation. CI calls the same commands, and a `windows-latest` job runs
  them on Windows.

## Consequences

- A module can be understood, tested, run and shipped on its own, and used from
  a ten-line script with no server, transport or event loop. The sample-replay
  example is the proof and the template.
- Adding a module or a source is one generator command and no edits to
  Dockerfile, compose or the workspace; the pipeline file is the only place that
  says what runs.
- The lock is one file, but a change to a member's manifest re-locks everyone,
  and the desktop package still needs its own `uv lock` and the
  `--upgrade-package p-swamp` step to be seen from the workspace.
- A module needs a models folder for its messages, so adding one touches two
  projects. We accept that for the one-way dependency.
- Many small projects mean more manifests and a longer cold `uv sync`. The
  layering test and the generators carry the cost of keeping them uniform.
- Sources are not hosted on the transport, so they cannot be moved to a worker
  of their own by configuration the way analysis modules can. A deployment that
  needs that writes a source that reads from a transport.
- The Windows promise needs maintaining: every command is exercised on a Windows
  runner, and the CLI avoids bare `python`, shell syntax and symlinks.
- The grid monitor (`pswamp_web/`) is untouched: it stays on its thread-based
  Hub/Bus with its models in the server, and moves to modules later.

## Alternatives considered

- **One project containing all modules, with subpackages.** The status quo.
  Cheaper to maintain, but it hides what a module depends on and cannot be
  installed one at a time.
- **Messages in each module's package.** Simple, and how it started, but
  consumers must import a module to read its type, which couples the server and
  other modules to analysis code and its dependencies.
- **Keep the module API async.** No change for the host, but it forces an event
  loop on every script and test. A sync `process` with an async wrapper serves
  both callers.
- **Sources as transport-hosted modules, uniformly.** Elegant on paper: a source
  is a module with `inputs = ()`, hosted by a worker like the others. Rejected:
  it puts every frame on a second hop, gives pacing (which is per client, for a
  person watching) a second clock, and turns a seek into a round trip. In-process
  sources keep the project shape, the entry point and the script call, and lose
  only worker placement.
- **Pipelines declared in Python.** The previous form. Code that is really data
  could not be validated without importing it, nor edited by someone who is not
  writing Python. TOML with entry points can.
- **Keeping the bash scripts, or adding PowerShell ones.** Two parallel sets,
  neither testable. One Python CLI is tested, cross-platform and shares its
  helpers.
- **The desktop package as a workspace member.** One lock for everything, at the
  price of solving Qt, Kafka and FastAPI as one dependency problem.
