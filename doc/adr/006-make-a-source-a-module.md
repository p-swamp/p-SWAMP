# ADR-006: Make a source a `Module` subclass, still run in its run's process

- Status: Accepted
- Date: 2026-10-07

## Context

ADR-005 made sources "modules": projects under `modules/`, found by their
`pswamp.modules` entry point, listed in a pipeline file. In the code, though,
`SourceModule` was a class tree of its own (`Configurable, ABC`), beside
`Module`, while the two contracts overlapped almost entirely: a `name`,
`outputs`, `commands`, no `inputs`, `validate` and a command handler. A module
with no inputs that only answers commands (`range-summary`) was already legal.
So "a source is a module" was true on disk and false in `issubclass`, and
`Playable` answered its commands in an `async handle`, the name `Module`
reserves for a synchronous answer.

## Decision

We will make `SourceModule` a subclass of `Module` (`SourceModule(Module,
Configurable)`): a source is a module with no inputs that produces messages. It
gets the module's `identity` and reports its settings as `parameters`.
`Playable` answers its commands in `ahandle`, the slot `Module` gives an answer
that awaits; it returns nothing, since a player answers through its sink.

Where a source runs does not change: in the process that owns its run, read by
the run's `ActiveSource` router, never in a `ModuleHost` on the transport, for
ADR-005's reasons (per-viewer pacing, a synchronous 409 for a refused player
command, no broker hop for the frame on screen). `Pipeline` now refuses a
source listed among its modules, so this holds for a pipeline declared in code
as well as one read from a file.

## Consequences

- One base class and one vocabulary for everything a pipeline names; a source
  can be inspected, documented and generated like any module.
- `run_command` on a playable source fails loudly ("the player is not
  running"): its player lives on the loop that ran `start`. There,
  `await source.arun_command(command)` applies it.
- A source inherits members it does not use (`overflow`, `maxsize`, `keep_up`,
  `join`); `blocking` means `read`/`coverage`/`open`/`close` run in a thread,
  where for a module it means `process`/`handle` do.

## Alternatives considered

- **Host every source on the transport**, like any other module: rejected again,
  for ADR-005's reasons.
- **Host only live sources in workers**: a plausible next step, since a live
  run's frames already cross the transport under `live.<source>`, but it needs
  a long-running hook `Module` does not have. Deferred until a real live feed
  needs its own process.
- **Leave the two trees apart**: keeps a distinction the docs deny, and a
  coroutine in `Module`'s synchronous `handle` slot.
