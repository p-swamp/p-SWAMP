# Server data architecture: open points

What is still wrong or undecided in the server data architecture (`models/`,
`core/`, `modules/`, `pipelines/`), for anyone building on its edges:
modules, CIM lookup, remote data sources and front-end pages. `AGENTS.md`
and `doc/server-data-architecture.md` say how the system works. This file
lists only what is open, and goes once the list is empty.

Issues are numbered 1 to 30 in the order "The issues" lists them, decisions
D1 to D13. Locations are given as file and symbol; line numbers drift.

---

## Next

- **D6, D2, D1, D13, D3**, in that order, one round each. Each changes what
  edge code is written against, so they land before more edge code is
  written.
- **Unscheduled, no decision needed:** 21 (worker probes) and 23
  (aiokafka's metadata spin), both Medium.
- **Deferred:** D5 (but write its additive-only rule down now), D7 to D12
  (until CIM work starts), the join and several `@on` inputs (1 and 4;
  marked experimental meanwhile, per D4), and every Low issue.

---

## What contributors can start on

**The line.** A module declares inputs and outputs and writes plain code; a
source writes `read` or `aread`. Neither sees the transport, runs, hosts or
the broker. Edge code imports `Module`, `SourceModule`, `Playable`,
`EnvSetting`, `TimeRange`, `SourceConformance`, `CommandRefused`, three time
helpers and `pswamp_models`, nothing else. A fix behind that line changes no
module or source. Messages keep pydantic's default (unknown fields ignored),
so an optional field added within `v1` does not break an older reader.

**What is not settled is what edge code is written against**: D1 to D3 and
D6 for modules, D7 to D10 for CIM lookup, D2 for settings names. Each is
decided and built before that kind of edge work starts.

| Work | Start now? | Waits for |
|---|---|---|
| Remote data source (a deployment's history service) | Yes. The integration is the HTTP contract, `doc/remote-data-integration-contract.md`; the service never touches the core. | D2 renames the settings (`REMOTE_URL`) before deployments are configured; D12 later. |
| Module, per frame, no settings | Yes. | D6 will move its imports to `pswamp_core`. |
| Module that keeps state | Yes: an instance lives as long as its run, `reset` clears what came from the stream, `teardown` releases what `setup` took, and a command marked `sticky` survives a worker restart. | |
| Module that runs periodically, takes settings or brings a dependency | Not yet. | D1 (output outside a call), D2 (settings), D3 (dependencies, shared code). |
| CIM lookup | Not yet. | D7 to D10; only D7 and D9 need code, both small. |
| Front-end page over the core | Yes. A page takes its types from the generated contract (`Wire['…']`, `doc/api/openapi.json`) and sends commands as POSTs; `pswamp new subapp` and `pswamp new module` write one. A control that is a module setting has its command marked `sticky`. | D13, for a page that lists events: `run.latest` keeps only the newest message of a class, so it needs a store at the edge, as the grid monitor's `AlarmStore`. |
| Grid monitor panel | Yes, on its own thread-based Hub and Bus (`pswamp_web/`; AGENTS.md, "Adding a p-SWAMP view"). | Moving its panels onto modules waits for the desktop analysis apps to be lifted into modules: §10.6 of `doc/WIP-context-port-from-qt-to-web-frontend.md`. |

**The CIM scope (decided).** A CIM plugin is a clean place to add CIM
lookup logic later. Its outcome is a reference id on the frame, not grid
data on the transport. The hook exists:
`CimReferenceEnricher.reference_for(header)`
(`core/src/pswamp_core/enrich.py`), called once per channel layout, cached,
stamped on every frame as `PmuHeader.cimReferenceId`, applied to every
source stream in every process that builds a `SourceSet`. Today it returns
the configured stub id.

---

## Decisions

Each: the question, what is there today, the options and the
recommendation.

**D1. Output outside a call.** Settles 2. Options: (a) a periodic hook,
`every = 1.0` and `tick(now)`, returning outputs as `process` does; (b) an
injected `publish`, handed to `setup`; (c) none, documented. Recommended:
(a). It keeps "return, don't emit" and covers watchdogs, periodic summaries
and windowed analyses (buffer in `process`, compute in `tick`). Open within
(a): whether `tick` may run in a thread while `process` keeps reading.

**D2. Configuration.** Settles 13. Today module settings are constants, the
pipeline file takes no settings, and sources read `{NAME}_{SETTING}` in one
namespace across apps (`REMOTE_URL`, `LIVE_PATH`). Options: (a) one style
for modules and sources: declared settings, values in the pipeline file
(`[modules.<name>]`, `[sources.<name>]`), app-scoped environment overrides
(`<APP>_<NAME>_<SETTING>`, beside the existing `<APP>_SOURCES`); (b)
environment only, app-scoped. Recommended: (a). It renames every deployed
setting, so it lands before remote-data teams configure deployments. A
module listed twice under two names follows from it.

**D3. Dependencies and shared code.** Settles 14 and 15. The image gets a
module's third-party dependencies only through the server's manifest, which
the generator edits; a module added by hand ships without them.
Recommended: a `pswamp check` step that every `modules/*` project is a
server dependency; and a home for shared code, `libs/<name>/` projects that
modules may depend on (the layering test allows module → lib, never module
→ module).

**D4. What is experimental.** Parks 1 and 4 until they are fixed. One call
at a time per instance is guaranteed (`Module._calling`). Recommended: mark
the join and several `@on` inputs experimental until 1 and 4 are fixed, in
the docstrings and `doc/module-cookbook.md`. Not written yet.

**D5. How messages change.** Settles no issue; the remote contract lists it
under "Not settled yet". Recommended: within a version, add optional fields
only; a breaking change is a new class or version, published beside the old
one during a move. Make "unknown fields ignored" explicit on `DataModel`
with a test, and have `pswamp check` flag a field removed or changed in
`pswamp_models` against a committed schema snapshot, as it does for the api
contract. Today "unknown fields ignored" is pydantic's implicit default,
with no test, and the api contract check covers 5 of the 20 message
classes: those that ride in socket messages, which leaves out the commands
and `ErrorEvent`. Deferred, but write the additive-only rule down now.

**D6. The public API.** Settles part of 16 (a module importing another
module gets caught). `pswamp_core/__init__.py` exports nothing.
Recommended: re-export the edge surface from `pswamp_core` (`Module`, `on`,
`Latest`, `SourceModule`, `Playable`, `EnvSetting`, `TimeRange`,
`CommandRefused`, `SourceConformance`, the time helpers, the CIM lookup
base), call everything else internal, and have the layering test hold
module and source code to it.

**D7. Installing a CIM lookup.** `PipelineConfig.__call__`
(`core/src/pswamp_core/pipeline_config.py`) hard-codes
`CimReferenceEnricher`; the pipeline file takes only `cim_reference`.
Recommended: `[enrich] cim = "<entry point>"` in a `pswamp.enrichers`
group, configured as in D2; `cim_reference` stays as the stub's setting.

**D8. What a lookup receives.** Today the layout only: no stream (`mRID`),
no source name, no time, so a recording from before a grid change cannot
get the old model's id. Recommended: a small frozen context object (header,
stream `mRID`, source name, the first frame's timestamp), so it can grow
without breaking a lookup.

**D9. I/O and failure.** Today a lookup is synchronous on the event loop
("no I/O"), and one that raises stops the stream. Recommended: an async
form, awaited once per new layout before its first frame goes out, plus
`open` / `aopen` for loading at start (as sources have); a failed lookup
passes the frame with no id and reports once per layout on the error tray.

**D10. How long an id holds.** Today per layout, for the life of the run.
Recommended: cache per (layout, stream); a lookup may return a validity
end, after which the next frame triggers a new lookup.

**D11. One id per layout or per column.** Recommended: one per layout now.
Under D5 a per-column list is an optional field added later without
breaking anyone. It also settles a doc mismatch: a source may carry its own
id (a recording made with one) and the lookup fills it only when absent,
which is what `enrich.py` does. What says otherwise:
`PmuHeader.cimReferenceId`'s description ("never by a source", and so
`doc/api/openapi.json` and `schema.ts`) and
`doc/remote-data-integration-contract.md` ("leave `cimReferenceId` out").

**D12. Remote data, later.** The remote contract's "Not settled yet" list:
authentication and TLS, limits, and models beyond `pmu.frame`. Recommended:
name the settings now (`<APP>_REMOTE_TOKEN`, a CA bundle) under D2, so
adding them is additive. Live data over a remote service is a second
contract, not this one.

**D13. One class, several producers.** Settles 12. Issue 12 suggests
refusing two producers of a class. The desktop analysis apps need the
opposite for events: every app reports a status and several raise alarms,
each onto one topic that one consumer reads (`AlarmSender` in
`desktop/src/pswamp/coordination/alarm_handling.py`). Options: (a) refuse,
and give each app status and alarm classes of its own; (b) allow several
producers for a class marked as an event stream (status, alarms), refuse it
for anything else; (c) allow it everywhere, as now. Recommended: (b). A
cycle is refused under every option. `run.latest` keeps only the newest
message of a class, so a page showing a stream needs a store at the edge,
as the grid monitor's `AlarmStore` is today.

---

## Open issues, by severity

"Settled by" names the decision that settles an issue; "—" needs none.

**High** (breaks a running deployment, or silently loses what a user asked
for): none open.

**Medium**: wrong in situations the project will soon reach, or a trap in
the module contract for the next module.

| # | Issue | Settled by |
|---|---|---|
| 21 | The workers have no probe | — |
| 23 | aiokafka spins on metadata while a broker comes and goes: up to 24 000 log lines/s, for up to 11 s | — |
| 14 | A module with a dependency of its own fails to import in the image | D3 |
| 12 | Two producers of one class, or a cycle, pass every check | D13 |
| 2 | A module cannot publish outside a call | D1 |
| 1 | The join builds its bundle at dequeue, so a joined module that is behind pairs a trigger with inputs from after it | D4 |
| 7 | `class X(SourceModule, Playable)` is accepted and half works | — |
| 4 | Several `@on` inputs share one drop-oldest queue | D4 |
| 11 | A non-playable history is pumped unpaced; the generator writes that shape | — |
| 13 | One flat namespace for source settings; modules cannot be configured | D2 |
| 18 | A generated source's pipeline file is loaded by nothing | — |
| 17 | The remote-data stub is in the image by an unchecked `.dockerignore` exception | — |

**Low**: edge cases, small leaks, tooling.

| # | Issue | Settled by |
|---|---|---|
| 26 | Playback offsets and steps are unbounded: 500s, or `OverflowError` on the tray | — |
| 20 | `MALLOC_ARENA_MAX=2` is set in the Dockerfile only; AGENTS.md does not mention it | — |
| 30 | A page closed during a push logs an unhandled `WebSocketDisconnect` | — |
| 28 | A run keeps playing for 300 s after its last socket closes | — |
| 24 | "Not delivered within 10 s" reaches the tray up to 2.7 s late | — |
| 25 | A process that starts without a broker exits with its producer unclosed | — |
| 22 | An outbox reports falling behind, never catching up | — |
| 3 | An input without a `timestamp` fails every body result | — |
| 5 | `missing="skip"` skips silently | — |
| 9 | "A source is a module" holds for the type, not the behaviour | — |
| 8 | A source's outputs past the first are half supported | — |
| 27 | The error tray keeps 20 notices per client id for ever | — |
| 15 | Code shared by two modules has no home | D3 |
| 16 | Three rules AGENTS.md calls test-enforced are not | D6 (part) |
| 19 | The generator's worker-list patterns are not bounded to their block | — |
| 10 | `SourceConformance` reads without `open()` | — |
| 6 | `Module` has no `abstract = True` | — |
| 29 | `useServerSocket.ts` says 1008 means "client id rejected"; it also means a path no app serves | — |

---

## The issues

What is wrong, where, why it matters, and a suggested fix, grouped by area.

### The module contract

**1. The join builds its bundle when the trigger is dequeued.**
- What: a joined module that is behind pairs trigger *t* with inputs that
  arrived after *t*, so its results depend on scheduling. That contradicts
  "a replay behaves exactly as the live feed it recorded" (the `inputs.py`
  docstring, ADR-005).
- Where: `ModuleHost` queues the raw trigger (`core/src/pswamp_core/host.py`);
  `Module` feeds the join when the call runs (`modules.py`); `Latest.feed`
  (`inputs.py`) bounds only how much *older* an input may be.
- Suggestion: build the bundle on arrival and queue that.
  `test_age_is_message_time_and_an_unstamped_or_newer_input_is_fresh`
  asserts today's rule.
- No module in the repo uses the join, and no test covers a slow joined
  module in a host.

**2. A module cannot publish outside a call.** There is no `emit()`, and
`setup()` takes no sink.
- No output without an input: a "no frames for N s" watchdog or a periodic
  summary cannot be written.
- Heavy work cannot keep reading while it computes. With `blocking = True`
  the instance takes no input during a call and the queue drops the oldest
  past 64, so a windowed analysis (mode estimation, islanding) gets gaps.
- ADR-006 names this as "a long-running hook `Module` does not have".
  Settled by D1.

**3. An input without a `timestamp` makes every body result fail
validation.** A body result is wrapped in an envelope stamped with its
input's time (`Module.outputs_of`), and the envelope requires one
(`models/src/pswamp_models/common/results.py`).

**4. Several `@on` inputs share one drop-oldest queue** (the host's slot in
`host.py`, `core/src/pswamp_core/subscription.py`). Behind a fast stream the
rare input is dropped with the frames: with two inputs and a queue of 8,
the rare one was never handled.

**5. `missing="skip"` skips silently.** A joined module whose other input
never arrives publishes nothing, with no log and no `ErrorEvent`.

**6. `Module` has no `abstract = True`** (a `SourceModule` has), so a base
class with inputs and no `process` is refused.

### Sources

**7. `class X(SourceModule, Playable)` is accepted and half works.**
- What: in that base order `commands` is `()`, and `ahandle` and `validate`
  are `Module`'s. The source starts and shows a frame; play then fails with
  `NotImplementedError` rather than a 409, and `pswamp modules list` says
  "not playable".
- Where: `Playable.__init_subclass__` (`core/src/pswamp_core/playable.py`)
  checks only `kind`.
- Suggestion: refuse a class whose `ahandle` is not `Playable.ahandle`
  ("list Playable first").

**8. A source's outputs past the first are half supported.**
- The class check and `SourceConformance` allow them.
- `PipelineConfig.source_models` (`pipeline_config.py`) counts only
  `cls.model` as produced, so a module reading a second output fails to
  load.
- `Playable` and `PipelineRun` treat every record as the frame at the
  cursor, and a follower of a live run subscribes to the primary output only
  (`PipelineRun._follow`).
- With one active source per run, the join's own example (pmu + scada + se)
  cannot be fed by sources.
- Suggestion: allow exactly one output for now, or finish it.

**9. "A source is a module" holds for the type, not the behaviour.**
- `setup()`, `teardown()` and `reset()` are never called on a source; only
  `ModuleHost` calls them.
- `commands` on a source that is not `Playable` pass the class check, and
  nothing routes them: `PipelineRun.dispatch` raises `NoReceiver`.
- `pswamp modules list` (`_list_modules` in `pipeline_config.py`) derives
  "playable" from `cls.commands`, not from `issubclass(cls, Playable)`:
  wrong for both cases above and for 7. The generated source test
  (`test___PKG___source.py.template`) also takes `commands` to mean
  playable.
- ADR-006 lists the members a source does not use; it does not list these.
- Suggestion: refuse `commands` on a non-playable source, and an overridden
  `setup`, at class creation.

**10. `SourceConformance`'s sync cases call `read()` and `coverage()`
without `open()`** (`core/src/pswamp_core/testing.py`), so both fail on a
source that needs it.

**11. A history that is not `Playable` is pumped whole and unpaced when made
active** (`ActiveSource._run_pump`). `pswamp new module --source` without
`--playable` generates that shape. The `active_source.py` docstring calls it
intended; once the pump ends, play is refused as "not playable".

### Pipelines, configuration and the image

**12. Two pipeline shapes pass every check.**
- Two modules publishing the same class: results interleave on one topic,
  and `run.latest` keeps whichever came last.
- A module reading a class it publishes, or a longer cycle: an unbounded
  loop. It passes because the producer check counts a module's own outputs
  as produced.
- Where: `Pipeline.__post_init__` (`core/src/pswamp_core/pipeline.py`). Two
  modules sending the same *command* is fine and stays allowed.
- `doc/module-cookbook.md` (on `pswamp pipelines validate`) says the first
  is refused. It is not. Settled by D13.

**13. A pipeline file says which modules run, not how they are set.**
`[[sources]]` takes `name` and `module` only (`pipeline_config.py`), and
modules take nothing. Source settings come from `{NAME}_{SETTING}` by
instance name, one flat namespace across apps (every generated module
pipeline names its source `live`). Module settings are constants in code,
so a module cannot be listed twice with different settings. Settled by D2.

**14. Per-module projects do not give per-module deployment.**
- `Pipeline.load` resolves every module and source the file names, in the
  server and in each worker, whatever `PSWAMP_WORKER_MODULES` says.
- The server learns a module's inputs and outputs from its class, so every
  module's dependencies are the server's.
- The Dockerfile installs modules with `--no-deps`; their third-party
  dependencies arrive only through `pswamp-server`'s list. A module added
  by hand with a dependency of its own works locally and fails to import in
  the image.
- ADR-005 rejects one shared project because it "cannot be installed one at
  a time"; nothing installs one at a time today. Settled by D3.

**15. Code shared by two modules has no home.** `sample.py` and
`sample_data.txt` are byte-identical in `sample-replay` and
`live-synthetic`, because a module may not import another. Settled by D3.

**16. Three rules AGENTS.md calls test-enforced are not** (under
"Conventions", the bullet on module folders).
- Test file names unique repo-wide: no test of its own. The one-session run
  (`pswamp test server`, and CI's) stops at collection on a duplicate
  basename; `pswamp test module <name>` alone does not.
- Messages live in `pswamp_models`, never in a module: no test.
- A module imports no other module: `tools/tests/test_tools_layering.py`
  sees what importing the `src/` package loads, not an import inside a
  function. D6 settles this one.

**17. The remote-data stub is in the image by a `.dockerignore` exception
no build step checks** (`!modules/remote-history/examples/remote_data_stub/`).
The Dockerfile's import check loads `server` only. Compose is started only
by the Playwright job, which is not required, and no CI job exercises the
k8s manifest.

**18. A source generated with `--source` gets a pipeline file that no
worker and no web app loads.** Nothing compares the workers' lists with the
pipeline files; `pswamp check` validates the files only.

**19. The generator's worker-list patterns are not bounded to their block**
(`WORKER_LIST_PATTERNS` in `tools/src/pswamp_tools/generate.py`). If
module-worker lost its variable, the pattern would patch batch-worker's
list, and `check-generators` reads back with the same pattern, so it would
pass. The comment beside them says they are anchored on the worker's own
name.

**20. `MALLOC_ARENA_MAX=2` is set in the Dockerfile only.** Without it each
pipeline the server builds leaves ~12 MB in glibc malloc arenas, and the
server is killed at its 768 MiB limit after about 60 new clients (the
Dockerfile's comment says why). Compose, k8s and a downstream build inherit
it from the image. What is open:
- AGENTS.md does not mention it, though its "peak RSS follows
  `MAX_PIPELINES`" holds only with it. It also says "both manifests size
  `limits.memory` from the cap"; there is one, `k8s/p-swamp-local.yaml`,
  and compose sets no limit.
- A server run outside the image (`uv run src/server.py`) does not get it,
  and no test checks that it is set.

### The Kafka transport and probes

**21. The workers have no probe.** The module and batch workers have none in
`k8s/p-swamp-local.yaml` or compose, so a wedged worker stays Running and
Ready. `/healthz` leaves the broker out on purpose (AGENTS.md, "One cheap
probe": a failing broker would take the grid monitor, which needs none, off
the Service). Its docstring (`server.py`) and the comment on the compose
server's healthcheck still say the server has no external dependencies;
with Kafka configured it has. Suggestion: let the transport's state reach a
worker probe, and fix the two comments.

**22. An outbox reports falling behind, never catching up.** Its
`KeepUpMonitor` is consulted only on a drop (`Outbox` in
`core/src/pswamp_core/transport/__init__.py`), so after an outage the
tray's last word on the live run is "cannot publish as fast as it
produces".

**23. aiokafka spins on metadata while a broker comes and goes.**
- What: the server and the module worker log `Unable to update metadata`,
  `Unable connect to node` and `Topic … not found in cluster metadata`
  thousands of times a second. Compose: 2 to 3 s at each stop, start or
  recreate of Kafka, up to 18 000 lines/s in the server, which peaks at
  ~90% CPU. Minikube: the server up to 24 000 lines/s for 1 to 2 s, and the
  worker ~9 000 lines/s for 10 to 11 s after a new Kafka pod (its
  `emptyDir` lost the topics the worker publishes to). It stops on its own.
- Where: aiokafka 0.14.0, `producer/sender.py` and `consumer/fetcher.py`.
  While a partition's leader is unknown, the loop forces a metadata update
  and waits for it, and a refused connection or a missing topic answers at
  once, so it loops with no backoff, though its comment says "wait backoff
  time". The publish that started it fails after `request_timeout_ms`
  (10 s); our `publish` then makes the topic again, which ends it.
- Why: a broker rollout floods every process's log and spends CPU on all of
  them.
- Options (none tried): re-create the topics a process publishes to as soon
  as its consumer finds topics missing, rather than when a publish times
  out; a logging filter that collapses aiokafka's repeats; a fix upstream.

**24. "Not delivered within 10 s" reaches the tray up to 2.7 s late.**
- What: with Kafka scaled to 0 in minikube, the report arrives 10.6 to
  12.7 s after the POST (10.1 s in compose).
- Where: `Outbox` gives up only once the attempt in progress returns, and in
  minikube an attempt takes up to the producer's 10 s request timeout. The
  receiver refuses a command older than 10 s, so a late attempt that
  succeeds is still not applied.
- By the code, an attempt whose topic was forgotten first makes the topic
  through the admin client (10 s timeout), then sends it: about 20 s at
  worst. Not measured.

**25. A process that starts without a broker exits with its producer
unclosed.**
- What: when every deployment in minikube restarts at once, the server
  restarts once and both workers twice ("Unable to bootstrap") before
  running, and the log shows "Unclosed AIOKafkaProducer".
- Where: `KafkaTransport.open` does not stop a producer whose `start()`
  failed. The exit itself is the intended fail-fast: `pswamp deploy
  minikube` rolls Kafka out first, and compose waits for its healthcheck.
- It exits only where the transport opens at start: the workers, and the
  server with a live source. A server with none opens it at a client's
  first connect. By the code (not run), each connect then fails with 1011,
  the client retries every 2 s, and each retry leaves an unclosed producer.

### The web API and pages

**26. Playback offsets and steps are unbounded.**
- A seek whose end is not after its start answers 500, not 422. `SeekBody`
  (`app/server-python/src/pmu_test_streamer/api.py`) lacks the check
  `SeekCommand` has (`models/src/pswamp_models/player/commands.py`), so the
  `ValidationError` is raised inside the handler.
- A step of `n = -10**15` answers 200 and reaches the tray as
  `OverflowError: date value out of range`: `StepBody.n` has no bound, and
  `Playable` adds the step to a datetime.
- `offset_s=1e15` answers 500, an `OverflowError` from `Playable.validate`;
  `end_offset_s=1e15` answers 200, then the tray reports the same
  `OverflowError`. Neither `SeekBody` nor `SeekCommand` bounds the offsets.
  A huge positive step is harmless: it plays to the end.
- Suggestion: bound both offsets and `StepBody.n` in the API, and give
  `SeekBody` `SeekCommand`'s check, so a value out of range is a 422.

**27. The error tray keeps the last 20 notices of every client id it has
seen, for the life of the process** (`app/server-python/src/errors/hub.py`).
A reused client id replays them.

**28. A run keeps playing for `idle_seconds` (300 s) after its last socket
closes** (`PipelineRegistry` in `core/src/pswamp_core/pipeline.py`). Seven
10x replays left that way held ~26% of a core in the server and ~33% in the
module worker. A new viewer was unaffected at this frame size.

**29. `app/client-web/src/hooks/useServerSocket.ts` says 1008 means "our
client id was rejected".** It also means a path no app serves
(`unknown_socket` in `server.py`).

**30. A page closed during a push logs an unhandled `WebSocketDisconnect`.**
- What: "Exception in ASGI application" from `time_window`'s socket, when
  `send_state` raises on a closing connection. Seen once in ~320 page
  closes at 6 at a time.
- Where: `_serve` in `app/server-python/src/pswamp_web/pump.py` suppresses
  only `CancelledError` from the push task. `connected_hub` still releases
  the pipeline in its `finally`, so nothing leaks; it is a traceback in the
  log.
- Only the grid monitor's pages: the streamer's `push_changes` (`shared.py`)
  already ignores `WebSocketDisconnect`.

---

## Reproducing

### In process: 1, 3, 7 and 12

Run from the repo root with `.venv/bin/python` (or paste into `python -`).
It prints:

```
1  trigger at t=10s, other input from t=58s -> bundled
3  input without timestamp -> ValidationError
7  class Wrong(SourceModule, Playable) accepted; commands = () | ahandle is Module's: True
12 two producers of BodyResult -> accepted
12 a module that reads its own output -> accepted
```

The first line is `Latest` alone, outside a host: an input newer than the
trigger counts as fresh, which is what pairs a late-dequeued trigger with
inputs from after it (1).

```python
from datetime import datetime, timezone, timedelta
from typing import Literal
from pydantic import BaseModel
from pswamp_models.common import DataModel, ResultEnvelope
from pswamp_core.modules import Module, Latest
from pswamp_core.sources import SourceModule
from pswamp_core.playable import Playable
from pswamp_core.pipeline import Pipeline

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

class Tick(DataModel):
    version: Literal["v1"] = "v1"
class Body(BaseModel):
    n: int
class BodyResult(ResultEnvelope[Body]): pass
class A(Module):
    name = "a"; inputs = (Tick,); outputs = (BodyResult,)
    def process(self, t): return Body(n=1)

# 1: an input newer than the trigger counts as fresh
class Fast(DataModel):
    version: Literal["v1"] = "v1"
class Slowly(DataModel):
    version: Literal["v1"] = "v1"
j = Latest(trigger="fast", max_age={"slow": 10.0}).bound({"fast": Fast, "slow": Slowly})
j.feed(Slowly(timestamp=T0 + timedelta(seconds=58)))
b = j.feed(Fast(timestamp=T0 + timedelta(seconds=10)))
print("1  trigger at t=10s, other input from t=58s ->", "bundled" if b else "skipped")

# 3: an input without a timestamp
try:
    A().run(Tick()); print("3  ok")
except Exception as e:
    print("3  input without timestamp ->", type(e).__name__)

# 7: the bases in the other order
class Wrong(SourceModule, Playable):
    name = "wrong"; kind = "history"
    def read(self, start=None, end=None): yield from ()
    def coverage(self): return None
print("7  class Wrong(SourceModule, Playable) accepted; commands =", Wrong.commands,
      "| ahandle is Module's:", Wrong.ahandle is Module.ahandle)

# 12: two producers of one class; a module reading what it publishes
class B(Module):
    name = "b"; inputs = (Tick,); outputs = (BodyResult,)
    def process(self, t): return Body(n=2)
class Echo(Module):
    name = "echo"; inputs = (BodyResult,); outputs = (BodyResult,)
    def process(self, r): return Body(n=r.result.n + 1)
for label, mods in (("two producers of BodyResult", (A, B)), ("a module that reads its own output", (A, Echo))):
    try:
        Pipeline("app", lambda: None, modules=mods, source_models=(Tick,)); print("12", label, "-> accepted")
    except Exception as e:
        print("12", label, "-> refused:", e)
```

### A stack beside your own: 23 to 26

Under its own project name and ports, so a developer's `p-swamp` stack on
:8000 is untouched:

```
docker build -t p-swamp:review .
docker compose -p pswamp-review -f docker-compose.yml -f compose.review.yml up -d --wait   # :8132
```

`compose.review.yml`:

```yaml
services:
  server:
    image: p-swamp:review
    build: !reset null
    ports: !override ["8132:8000"]
    command: !override ["python", "server.py"]
  module-worker: {image: p-swamp:review, build: !reset null}
  batch-worker: {image: p-swamp:review, build: !reset null}
  remote-data-stub: {image: p-swamp:review, build: !reset null}
  kafka:
    ports: !override ["19192:19092"]
    environment:
      KAFKA_ADVERTISED_LISTENERS: "PLAINTEXT://kafka:9092,EXTERNAL://localhost:19192"
```

Below, `dc` is `docker compose -p pswamp-review -f docker-compose.yml -f
compose.review.yml`, and `<id>` is the client id of a page open at
http://127.0.0.1:8132/pmu-test-streamer. Use a fresh id for each check, or
the tray replays old notices (27).

- **23**: `dc up -d --force-recreate --no-deps --wait kafka`, then
  `dc logs server | tail`: the burst.
- **24**: `dc stop kafka`, press play, and time the tray's "not delivered"
  notice against the POST. In minikube: `kubectl scale deploy/p-swamp-kafka
  --replicas=0`.
- **25**: in minikube, `kubectl rollout restart deploy` (every deployment at
  once), then the server and workers' logs.
- **26**: `curl -X POST
  'localhost:8132/api/pmu-test-streamer/playback/seek?client_id=<id>' -H
  'content-type: application/json' -d '{"offset_s": 10, "end_offset_s":
  5}'`: 500. `-d '{"offset_s": 1e15}'` answers 500 too.

In minikube: `uv run pswamp deploy minikube --no-browser --no-logs`, then
`kubectl port-forward service/p-swamp 30080:8000` and the page at
http://127.0.0.1:30080/pmu-test-streamer.
