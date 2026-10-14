# Review comments: module contract changes on `e2e-refactor-organisation-louis`

For Louis. Scope: the models package, the module API and join, one project per
module, TOML pipelines, sources as modules, and their docs (`deef05a` to
`dbf635b`).

How it was reviewed: `core/src/pswamp_core/`, the models bases and the six
projects under `modules/` were read in full; compose, k8s, the Dockerfile, the
docs and the generator were read against that code. Comments 1 to 4, 9 and 13
were reproduced with the script in the appendix. The test suites were not run
then; on 2026-10-14 the branch was run end to end (comments 28 to 39, under
"Running it").

Compose, k8s and the pipeline file agree with the code today, and the module
index in `modules/README.md` matches all six projects.

---

## By severity, at `dbf635b`

Every comment below, ranked. "Before" means it was already there at `069f88f`,
before this review's scope; "Louis" means it came with `f70d7d6` to `dbf635b`.
Comment 39 is about the refused-socket change (`924221e`), not Louis's commits,
and is left out. Retested at
`16f36a5`: all still present except 23 to 27, which are fixed (see "Retest at
`16f36a5`").

**High**: breaks a running deployment, or silently loses what a user asked for.

| # | Issue | Origin |
|---|---|---|
| 28 | Kafka losing its topics stops the stack until every process restarts; probes stay green | before |
| 29 | A live source that fails stays failed; later viewers are not told | before |
| 31 | A command sent during a broker outage is acknowledged, then lost or applied late | before |
| 30 | Module state belongs to the key: settings lost on a worker restart, inherited after a crash | before |

**Medium**: wrong in situations the project will soon reach, or a trap in the
module contract for the next module.

| # | Issue | Origin |
|---|---|---|
| 32 | A hung remote data service holds up every command of the run | before |
| 1 | A `blocking` module runs `process` and `handle` in two threads at once | Louis |
| 2 | A sync `read` source holds the event loop; a live one would freeze the server | Louis |
| 11 | A module with a dependency of its own fails to import in the image | Louis |
| 33 | The models layering test fails, so the unit tests are red | Louis |
| 6 | No teardown hook: a resource leaks per evicted key | before |
| 9 | Two producers of one class, or a cycle, pass every check | before |
| 5 | A module cannot publish outside a call | Louis |
| 3 | The join builds its bundle at dequeue; an input from after a seek back stays fresh | Louis |
| 4 | `class X(SourceModule, Playable)` is accepted and half works | Louis |
| 14 | Several `@on` inputs share one drop-oldest queue | Louis |
| 18 | A non-playable history is pumped unpaced; the generator writes that shape | Louis |
| 10 | One flat namespace for source settings; modules cannot be configured | Louis |
| 21 | A generated source's pipeline file is loaded by nothing | Louis |
| 20 | The remote-data stub is in the image by an unchecked `.dockerignore` exception | Louis |

**Low**: edge cases, small leaks, tooling.

| # | Issue | Origin |
|---|---|---|
| 38 | A run keeps playing for 300 s after its last socket closes | before |
| 36 | An outbox reports falling behind, never catching up | before |
| 34 | A seek whose end is not after its start answers 500 | before |
| 35 | A huge negative step reaches the tray as `OverflowError` | before |
| 13 | An input without a `timestamp` fails every body result | before |
| 15 | `missing="skip"` skips silently | Louis |
| 8 | "A source is a module" holds for the type, not the behaviour | Louis |
| 7 | A source's outputs past the first are half supported | Louis |
| 37 | The error tray keeps 20 notices per client id for ever | before |
| 12 | Code shared by two modules has no home | Louis |
| 19 | Three rules AGENTS.md calls test-enforced are not | Louis |
| 22 | The generator's worker-list patterns are not bounded to their block | Louis |
| 16 | `SourceConformance` reads without `open()` | Louis |
| 17 | `Module` has no `abstract = True` | Louis |

**Docs and wording**: 23 to 27 (Louis). Fixed in `16f36a5`; see the note under
"Docs and wording".

---

## Defects

**1. A `blocking` module runs `process` and `handle` in two threads at once.**
- Where: `core/src/pswamp_core/modules.py:383` (`_call`),
  `core/src/pswamp_core/host.py:268` and `:289` (inputs and commands are two
  tasks per instance).
- Why: the contract says "write synchronous code". With `blocking = True` an
  input and a command are inside the same instance together, with no lock.
  State both touch (the shape of excursion's `auto_pause` and counters) is
  raced. A non-blocking module is safe, since both run on the loop.
- Suggestion: one lock per instance around the handler call in `arun` and
  around `ahandle` where the host calls it (`host.py:120`).

**2. A source written as sync `read` never yields to the event loop.**
- Where: `core/src/pswamp_core/sources.py:251-260`. Callers:
  `modules/range-summary/src/pswamp_modules/range_summary/module.py:49`,
  `core/src/pswamp_core/active_source.py:212`.
- Why: a range read holds the loop for its whole length; with the in-memory
  transport every socket and every other run waits. Measured: 200 000 records,
  0.43 s, another task got 0 turns. A *live* source written as `read` with the
  default `blocking = False` would hold the loop for good, and no class check
  refuses it.
- Suggestion: `await asyncio.sleep(0)` every N records in the inline path;
  refuse `kind = "live"` with a sync `read` unless `blocking = True`.

**3. The join builds its bundle when the trigger is dequeued.**
- Where: `host.py:244` queues the raw trigger; `modules.py:371` feeds the join
  when the call runs; `core/src/pswamp_core/inputs.py:162-166` bounds only how
  much *older* an input may be.
- Why: (a) a joined module that is behind pairs trigger *t* with inputs from
  after *t*, so results depend on scheduling. That contradicts "a replay
  behaves exactly as the live feed it recorded" (`inputs.py:26-28`, ADR-005).
  (b) After a seek backwards, an input from before the seek stays fresh:
  trigger at 10 s, other input from 58 s, `max_age` 10 s, bundled. Nothing
  resets a module on a seek or a source switch.
- Suggestion: (a) build the bundle on arrival and queue that. (b) is your
  call: an input far ahead of the trigger counts as stale, or a seek resets
  module state. `test_age_is_message_time_and_an_unstamped_or_newer_input_is_fresh`
  asserts today's rule.
- Note: no module in the repo uses the join; no test covers a slow joined
  module in a host.

**4. `class X(SourceModule, Playable)` is accepted and half works.**
- Where: `core/src/pswamp_core/playable.py:115-118` checks only `kind`.
- Why: in that base order `commands` is `()`, and `ahandle` and `validate` are
  `Module`'s. The source starts and shows a frame, every playback command then
  fails, and `pswamp modules list` says "not playable".
- Suggestion: in `Playable.__init_subclass__`, refuse a class whose `ahandle`
  is not `Playable.ahandle` ("list Playable first").

## Gaps in the contract

**5. A module cannot publish outside a call.** `setup(out)` lost its `out` and
there is no `emit()` (`modules.py:234`).
- No output without an input: a "no frames for N s" watchdog or a periodic
  summary cannot be written.
- Heavy work cannot keep reading while it computes. With `blocking = True` the
  instance takes no input during a call and the queue drops the oldest past
  64, so a windowed analysis (mode estimation, islanding) gets gaps.
- ADR-006 already names "a long-running hook `Module` does not have". Worth a
  decision: a publish hook, or a written pattern (return the finished result
  from a later call, in a hand-built envelope).

**6. No teardown hook.** `setup()` exists; nothing is called when a host drops
an instance (`host.py:317-329`). A module holding a thread, a file or a model
leaks one per evicted key. Sources have `open`/`close`. Older than this
branch; now the two halves of "a module" differ.

**7. A source's `outputs` past the first are half supported.**
- The class check and `SourceConformance` allow them.
- `core/src/pswamp_core/pipeline_config.py:199` counts only `model` as
  produced, so a module reading a second output fails to load.
- `playable.py:395-396` and `core/src/pswamp_core/pipeline.py:287-288` treat
  every record as the frame at the cursor; a follower of a live run subscribes
  to the primary only (`pipeline.py:323`).
- With one active source per run, the join's example (pmu + scada + se) has no
  way to be fed by sources. Suggestion: allow exactly one output for now, or
  finish it.

**8. "A source is a module" holds for the type, not the behaviour.**
- `setup()` is never called on a source (only `host.py:287` calls it).
- `commands` on a source that is not `Playable` pass the class check and
  nothing routes them: `pipeline.py:343-346` raises `NoReceiver`.
- `pipeline_config.py:287` derives "playable" from `cls.commands`, not from
  `issubclass(cls, Playable)`: wrong for both cases above and for comment 4.
- ADR-006 lists the unused members; it does not list these.
- Suggestion: refuse `commands` on a non-playable source and an overridden
  `setup` at class creation.

**9. Two pipeline shapes pass every check.**
- Two modules publishing the same class: results interleave on one topic and
  `run.latest` keeps whichever came last.
- A module reading a class it publishes, or a longer cycle: an unbounded loop.
- Where: `pipeline.py:122-152`. Two modules sending the same *command* is
  fine and should stay allowed.
- `doc/module-cookbook.md:745-746` already says the first is refused.

**10. A pipeline file says which modules run, not how they are set.**
`[[sources]]` takes `name` and `module` only (`pipeline_config.py:93-99`);
modules take nothing. Source settings come from `{NAME}_{SETTING}` by instance
name, one flat namespace across apps (every generated module pipeline names
its source `live`). Module settings are constants in code. A module cannot be
listed twice with different settings.

**11. Per-module projects do not give per-module deployment.**
- `Pipeline.load` resolves every module and source the file names
  (`pipeline_config.py:133,139`), in the server and in each worker, whatever
  `PSWAMP_WORKER_MODULES` says.
- The server learns a module's inputs and outputs from its class, so every
  module's dependencies are the server's.
- `Dockerfile:197` installs modules with `--no-deps`; their third-party
  dependencies arrive only through `pswamp-server`'s list (`Dockerfile:149`).
  A module added by hand with a dependency of its own works locally and fails
  to import in the image.
- ADR-005 rejects one shared project because it "cannot be installed one at a
  time"; nothing installs one at a time today.

**12. Code shared by two modules has no home.** `sample.py` and
`sample_data.txt` are byte-identical in `sample-replay` and `live-synthetic`,
because a module may not import another.

## Smaller

**13.** An input without a `timestamp` makes every body result fail validation
(`modules.py:335`; `models/src/pswamp_models/common/results.py:42`).

**14.** A module with several `@on` inputs has one drop-oldest queue for all of
them (`host.py:151`, `core/src/pswamp_core/subscription.py:71`): behind a fast
stream the rare input is dropped with the frames.

**15.** `missing="skip"` skips silently: a joined module whose other input
never arrives publishes nothing, with no log and no `ErrorEvent`.

**16.** `SourceConformance`'s sync cases call `read()` and `coverage()` without
`open()` (`core/src/pswamp_core/testing.py:153-169`, `:200-206`).

**17.** `Module` has no `abstract = True` (a `SourceModule` has): a base class
with inputs and no `process` is refused.

**18.** A history that is not `Playable` is pumped whole and unpaced when made
active (`active_source.py:190`). `pswamp new module --source` without
`--playable` generates that shape.

## Deployment and the layout rules

**19. Three rules AGENTS.md calls test-enforced are not** (`AGENTS.md:1316-1319`).
- Test file names unique repo-wide: no test.
- Messages live in `pswamp_models`, never in a module: no test.
- A module imports no other module: `tools/tests/test_tools_layering.py:124`
  sees what importing the `src/` package loads, not an import inside a function.

**20. The remote-data stub is in the image by a `.dockerignore` exception no
build step checks** (`.dockerignore:53-56`). The Dockerfile's import check
loads `server` only. Compose is started only by the Playwright job, which is
not required; no CI job exercises the k8s manifest.

**21. A source generated with `--source` gets a pipeline file that no worker
and no web app loads.** Nothing compares the workers' lists with the pipeline
files; `pswamp check` validates the files only.

**22. The generator's worker-list patterns are not bounded to their block**
(`tools/src/pswamp_tools/generate.py:66-69`). If module-worker lost its
variable, the pattern would patch batch-worker's list, and `check-generators`
reads back with the same pattern, so it would pass.

## Docs and wording

Fixed 2026-10-14 in `16f36a5`. Comments 23 to 27 as below,
plus the same leftovers elsewhere: `FrameTable.tsx` (the gateway), the `pswamp
pipelines validate` help (a data client), the "spec loading" line in
`server-data-architecture.md`, `core/pyproject.toml`, `models/pyproject.toml`
and `models/src/pswamp_models/__init__.py` (a data provider), and "code and
tests in one folder" under "Adding a module". The api contract was regenerated
for the `cimReferenceId` description. "Provider" is kept where it means the
outside system a source reads from.

**23.** The docs say a host calls `arun_command`
(`doc/server-data-architecture.md:335-336`, `AGENTS.md:527-528`,
`modules.py:60-61`). Nothing calls it: the host calls `validate`, `ahandle`
and `answer_of` (`host.py:117-131`).

**24.** Where a source runs is said four ways: "the process that owns its run"
(ADR-006), "the server or the worker that owns the run"
(`server-data-architecture.md:425`), "the server or the worker that reads
them" (`AGENTS.md:552`), "the router lives in the server"
(`server-data-architecture.md:561`). In code only the server builds a run.

**25.** ADR-005:77-79: a new module needs "no edits to Dockerfile, compose or
the workspace". The generator edits compose, k8s and the server manifest
(`generate.py:346-408`).

**26.** Snippets and tables:
- `server-data-architecture.md:334`: `run_command(AutoPauseCommand(...))` on a
  `FrameStatsModule`, which takes no commands.
- `server-data-architecture.md:191`: `mean_hz`; the field is `mean_frequency_hz`.
- `modules/excursion/README.md:15-16`, `modules/range-summary/README.md:14`:
  topics `pause`, `auto.pause`, `summarize.range`; the real ones end `.command`.
- `module-cookbook.md:699`: `MyRecording`; the generator writes `MyRecordingSource`.
- `server-data-architecture.md:832-834`: "its pipeline in `modules/`"; it is
  `pipelines/`.
- `modules/sample-replay/README.md:10` lists "loop" as a command; there is none.

**27.** Wording left from the removed design:
- `models/src/pswamp_models/pmu/frame.py:62`: "Set by the gateway, never by a
  provider" (published in `doc/api/openapi.json` and `schema.ts`).
- `app/client-web/src/pages/pmu-test-streamer/PmuTestStreamerPage.tsx:78`:
  "provider → gateway → player → frame".
- `core/src/pswamp_core/worker.py:91`: the hint names
  `pipelines/pmu-test-streamer.toml`; the workers run from `pipelines/`.
- `core/src/pswamp_core/settings.py:13-15`: "the transport and data providers
  are configured this way"; only the transport is now.

---

## Running it (2026-10-14)

What was run: `dbf635b` plus a change, then uncommitted and since committed as
`924221e`, that refuses an unservable socket by accepting it and closing it
with 1008 (`refuse_socket`, `unknown_socket`). In three setups: the image under a bare `docker run`
(in-memory transport), the compose stack (Kafka, both workers, the remote
stub), and minikube (`pswamp deploy minikube`, `k8s/p-swamp-local.yaml`).
Steps to reproduce are in the appendix.

Unlike comments 1 to 27, these are about the branch as a whole: all but 33 and
39 were already there at `069f88f`, before this review's scope (see "At
`069f88f`" below).

### Regression

- `pswamp check`: passes.
- `pswamp test server`: 442 passed, 42 skipped, 1 failed (comment 33).
- `pswamp check-generators`: the generated tree passes `pswamp check`; its
  tests fail on comment 33 only.
- `pswamp test smoke`: passes, bare, compose and minikube.
- Playwright (`E2E_BASE_URL`): 11 passed bare, 12 compose, 12 minikube. The
  rest skip by design: no remote source bare, and "a provider that goes away"
  runs only against compose on :8000, so it was done by hand (comment 32).
- Every route (the monitor, its five focused views, the streamer, the
  reference page, an unknown path), in headless Chromium and Firefox, in all
  three setups: renders, no console errors. The monitor opens five data
  sockets plus the tray's.
- The appendix script prints the same as before for comments 1, 2, 3, 4, 9
  and 13.

### Defects seen end to end

**28. Kafka losing its topics stops the stack until every process is restarted.**
- Seen (compose, the Kafka container recreated, so its topics are gone): a new
  client gets its first frame; play and switch answer 200 and are never
  applied; no module result arrives. Still so a minute later. The server and
  both workers sit at ~70% CPU each, the server logging ~34 000 lines/s of
  `Topic … not found in cluster metadata`; `/healthz` answers ok throughout.
  Restarting the server and both workers recovers. A broker stopped and
  started with its topics kept recovers on its own.
- Seen (minikube, the Kafka pod deleted, so its `emptyDir` goes too): the
  same, still so two minutes later. Every pod stays Running and Ready with no
  restart; the server logs ~16 000 lines/s, and the server, both workers and
  Kafka use ~1.4 of the node's 2 CPUs. `kubectl rollout restart` of the
  server and both workers recovers.
- Where: `core/src/pswamp_core/transport/kafka.py:126`: `_created` remembers a
  topic for the life of the process, so neither `publish` nor the consumer's
  re-assignment (`:172`, `:199`) creates it again. aiokafka retries the
  missing metadata without raising, so `_consume`'s reconnect never runs. Each
  failed publish takes ~10 s, so an outbox moves one message per 10 s.
- Why: `k8s/p-swamp-local.yaml:276` runs Kafka on an `emptyDir`, so any new
  Kafka pod (a rollout, an eviction) loses the topics. The server's probes
  (`/healthz`, `:69`, `:77`) never notice, and the workers have none.
- Suggestion: forget a topic in `_created` on `UnknownTopicOrPartitionError`,
  and re-create every topic when the consumer finds one missing. Let the
  transport's state reach a probe.

**29. A live source that fails stays failed until the server restarts, and whoever switches to it later is not told.**
- Seen (in process, a live source that raises after 20 frames): the shared
  run ends with the error, and nothing starts it again. A client that switches
  to live afterwards reports `mode="live"`, `ended=False`, `error=None` and gets
  no frame. The `ErrorEvent` reached only the clients watching when it failed.
- Where: `core/src/pswamp_core/active_source.py:209-233` (`_run_pump` ends in
  `_fail`, and a live source has no play to retry with). A follower subscribes
  to the live run's frames and results, not its `PlayerStatus`
  (`core/src/pswamp_core/pipeline.py:323`).
- Why: a live PMU connection drops; today one drop ends live mode for every
  client.
- Suggestion: reopen a live stream with backoff in its shared run; publish the
  shared run's `PlayerStatus` and show it to followers.

**30. Module state belongs to the key, not to the run.**
- Seen (compose, excursion's `auto_pause` and count): after a module-worker
  restart, auto-pause is off again and nothing says so; the page's checkbox
  flips back on the next result, and the player no longer pauses at the trip.
  After a server crash (`docker kill`), the new run of the same browser gets
  the old instance: auto-pause still on, the count going on from 12. The same
  in minikube (the module-worker pod deleted; the server container killed,
  exit 137, restarted in its pod).
- Where: `core/src/pswamp_core/host.py:251-261` builds an instance per key on
  its first message; only `PipelineClosed` (`:246`) or 300 s without input
  (`:301`) drops it. The key is the client id, stable per browser, and a crash
  sends no `PipelineClosed`.
- Why: with comments 3(b) and 6, a module cannot tell a new run, a seek or a
  lost instance from more of the same stream. A setting the user made lives
  only in a worker's memory.
- Suggestion: a run id in the key, or on every message, so a host builds a
  fresh instance for a new run; the run re-sends module settings when an
  instance is rebuilt.

**31. A command sent while the broker is down is acknowledged, then lost or applied late, and the tray cannot say which.**
- Seen (compose, Kafka stopped for 20 s): `speed` and `play` answer 200 and
  are never applied once the broker is back.
- Seen (minikube, the Kafka container killed and restarted in its pod, topics
  kept): `speed` is dropped after ~10 s (`NodeNotReadyError`); `play`, queued
  behind it, is applied 24 s after its 200.
- Nothing reaches the error tray, which is fed through the same transport. A
  client connected through the outage works again afterwards.
- Where: `core/src/pswamp_core/transport/__init__.py:289-299` (a failed publish
  is counted and dropped); a reconnecting consumer starts every topic at its
  end (`kafka.py:172`, `:206`).
- Note: this is "nothing reports a command that never reaches its receiver"
  (`dispatch_command` in `app/server-python/src/shared.py`), now reproduced.

**32. A remote data service that hangs holds up every command of the run.**
- Seen (compose, the stub frozen with `docker pause`): a seek waited 10 s, the
  page showing "playing" meanwhile; a switch back to `sample`, acknowledged at
  once, was applied only after it. A stub that is stopped is reported within
  ~1.5 s, and play resumes once it is back. The same in minikube (the stub's
  container paused, then killed, in the node).
- Where: `modules/remote-history/src/pswamp_modules/remote_history/source.py:73`
  (coverage: a fixed 10 s timeout; a query waits up to `REMOTE_TIMEOUT`,
  30 s). A run applies its commands one at a time
  (`core/src/pswamp_core/command_routing.py:100-103`), and `ActiveSource.handle`
  awaits the playable source (`active_source.py:168`).
- Suggestion: a `SwitchSourceCommand` cancels the command in progress; the
  coverage timeout becomes a setting.

### Regression and smaller

**33. `test_the_models_import_pydantic_only` fails.** pydantic's
`_internal._validators` imports `zoneinfo`, which loads `sysconfig` and
`_sysconfigdata_<platform>`, a name not in `sys.stdlib_module_names`
(`models/tests/test_models_layering.py:29`). Fails on macOS (python.org
3.11.6) and with the image's Python (3.11.14, Linux). CI's uv-managed 3.11
was not tried; it takes the same path. Suggestion: skip names starting
`_sysconfigdata`.

**34.** A seek whose end is not after its start answers 500, not 422.
`SeekBody` lacks the check `SeekCommand` has
(`models/src/pswamp_models/player/commands.py:58-61`), so the
`ValidationError` is raised inside the handler
(`app/server-python/src/pmu_test_streamer/api.py:145-154`).

**35.** A step of `n = -10**15` answers 200 and reaches the tray as
`OverflowError: date value out of range`
(`core/src/pswamp_core/playable.py:242`). `StepBody.n` has no bound.

**36.** An outbox reports falling behind, never catching up: its
`KeepUpMonitor` is consulted only on a drop
(`core/src/pswamp_core/transport/__init__.py:274`). After an outage the tray's
last word on the live run is "cannot publish as fast as it produces".

**37.** The error tray keeps the last 20 notices of every client id it has
seen, for the life of the process (`app/server-python/src/errors/hub.py:64`).

**38.** A run keeps playing for `idle_seconds` (300 s) after its last socket
closes (`core/src/pswamp_core/pipeline.py:518-525`). Seven 10x replays left
that way held ~26% of a core in the server and ~33% in the module-worker. A
new viewer was unaffected at this frame size.

**39.** `app/client-web/src/hooks/useServerSocket.ts:22` says 1008 means "our
client id was rejected". Since `924221e` it also means a path no app serves.

### Looked for and not found

- A module instance left behind when its run stops: none in 30 runs, in
  memory and over Kafka.
- Results falling behind frames: at 10x over Kafka, 99% of pushes carry the
  frame's stats.
- A late auto-pause: at 10x over Kafka, the player stops one frame after the
  trip.
- The grid monitor's threads disturbing the core's pacing: with 0 to 8 monitor
  viewers, the streamer's frame gap stays 50 ms and `/healthz` 2 ms.
- The run cap failing: 8 served, the 9th and 10th closed with 1013.
- The k8s limits being too tight: in minikube, at both caps at once (8 monitor
  viewers, 8 streamers at 10x) for a minute, the server peaks at ~505 MiB of
  its 768 MiB and 60-80% of a core; no restart, refusal or tray notice.

### At `069f88f`, before this review's scope

`069f88f` is the last commit before `f70d7d6`, where this review's scope
begins. Run the same way, in compose and minikube, from a worktree with its own
scripts (`scripts/e2e-smoke-test.sh`,
`scripts/start-pswamp-in-local-minikube-cluster.sh`); the Playwright specs are
byte-identical to today's.

- Regression: green. Unit tests 160 passed, 28 skipped; the smoke script and
  12 Playwright specs pass (1 skipped) in both setups; every route renders in
  Chromium and Firefox.
- Comments 28 to 32 and 34 to 38 reproduce, with the same numbers (29 with
  the script rewritten for that commit's `DataClient` and `Player`; 37 seen in
  the code, not run). The code
  behind each has the same shape there: `_created` in `kafka.py`, the
  per-key slots in `host.py`, the outbox's drop, the 10 s timeouts in the
  remote data client, `SeekBody`.
- Comment 33 does not apply (`pswamp_models` and its test came later);
  comment 39 is about the refused-socket change (`924221e`).
- At both caps in minikube the server peaked at ~586 MiB of 768 MiB, against
  ~505 MiB today.

### Retest at `16f36a5` (2026-10-14)

`16f36a5` is `dbf635b` plus two commits: the refused-socket change
(`924221e`) and the fixes for comments 23 to 27 (`16f36a5`). Everything above
was run again, in bare, compose and minikube.

- Regression: as before. `pswamp check` passes; `pswamp test server` 442
  passed, 42 skipped, 1 failed (33); `check-generators` fails on 33 only;
  smoke passes in all three; Playwright 11 bare, 12 compose, 12 minikube; every
  route clean in Chromium and Firefox in all three. Minikube at both caps:
  server peak ~542 MiB of 768 MiB, no restart.
- Comments 1 to 22: all still present. Executed this time where the first pass
  only read the code: 5, 6, 7, 8, 10, 12, 14 (two `@on` inputs, queue of 8:
  43 dropped, the rare input never handled), 15 (20 triggers, nothing
  published, no log), 16 (both sync cases fail on a source that needs
  `open()`), 17, 18 (240 frames of 12 s published in 0.1 ms), 19 (an import
  inside a function is not seen), 22 (the pattern patches batch-worker's list
  once module-worker lacks the variable). 11, 20 and 21 were read again.
- Comments 23 to 27: fixed; no old wording left.
- Comments 28 to 38: all still present, with the same numbers: 28, 30, 31
  and 32 in compose and minikube; 29 in process; 34, 35 bare; 36, 38 compose;
  37 in the code.
- Comment 33: still fails.

---

## Appendix: reproductions

Run from the repo root: `.venv/bin/python repro.py` (or paste into
`python -`). Observed on `dbf635b`:

```
1  blocking module: process/handle overlapped = True | threads: 2
4  class Wrong(SourceModule, Playable) accepted; commands = () | ahandle is Module's: True
2  read 200000 records in 0.43s; other task ran 0 times meanwhile
9  two producers of BodyResult -> accepted
9  a module that reads its own output -> accepted
13 input without timestamp -> ValidationError
3  trigger at t=10s after a seek back, other input from t=58s -> bundled as fresh
```

```python
import asyncio, threading, time
from datetime import datetime, timezone, timedelta
from typing import Literal
from pydantic import BaseModel
from pswamp_models.common import DataModel, Command, ResultEnvelope
from pswamp_core.modules import Module, Latest
from pswamp_core.host import serve_module, command_inbox
from pswamp_core.subscription import Subscription, Overflow
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.playable import Playable
from pswamp_core.time_range import TimeRange
from pswamp_core.pipeline import Pipeline

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

class Tick(DataModel):
    version: Literal["v1"] = "v1"
class Body(BaseModel):
    n: int
class BodyResult(ResultEnvelope[Body]): pass
class PokeCommand(Command): pass

# 1: a blocking module, an input and a command at once
class Slow(Module):
    name = "slow"; inputs = (Tick,); outputs = (BodyResult,); commands = (PokeCommand,); blocking = True
    def __init__(self):
        super().__init__(); self.inside = 0; self.overlap = False; self.threads = set()
    def _enter(self):
        self.threads.add(threading.current_thread().name)
        self.inside += 1
        if self.inside > 1: self.overlap = True
        time.sleep(0.15); self.inside -= 1
    def process(self, tick): self._enter(); return Body(n=1)
    def handle(self, command): self._enter(); return Body(n=2)

class Own:
    def _detach(self, s): pass
class Out:
    def publish(self, m): pass

async def one():
    m = Slow(); out = Out()
    inputs = Subscription(Own(), (Tick,), Overflow.DROP_OLDEST, 64)
    commands = Subscription(Own(), (PokeCommand,), Overflow.GROW, 0)
    inbox = command_inbox(m, commands, out); inbox.start()
    task = asyncio.create_task(serve_module(m, inputs, out))
    inputs.offer(Tick(timestamp=T0)); await asyncio.sleep(0.03); commands.offer(PokeCommand())
    await asyncio.sleep(0.5); task.cancel(); await inbox.stop()
    print("1  blocking module: process/handle overlapped =", m.overlap, "| threads:", len(m.threads))
asyncio.run(one())

# 4: the bases in the other order
class Wrong(SourceModule, Playable):
    name = "wrong"; kind = "history"
    def read(self, start=None, end=None): yield from ()
    def coverage(self): return None
print("4  class Wrong(SourceModule, Playable) accepted; commands =", Wrong.commands,
      "| ahandle is Module's:", Wrong.ahandle is Module.ahandle)

# 2: a sync source read through a SourceSet
class Big(SourceModule):
    name = "big"; kind = "history"; outputs = (Tick,)
    def read(self, start=None, end=None):
        for n in range(200_000):
            yield Tick(timestamp=T0 + timedelta(milliseconds=n))
    def coverage(self): return TimeRange(T0, T0 + timedelta(seconds=200))

async def two():
    ticks = 0
    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.001); ticks += 1
    t = asyncio.create_task(ticker()); await asyncio.sleep(0.01); before = ticks
    began = time.perf_counter(); n = 0
    async for _ in await SourceSet([Big()]).consume(): n += 1
    print(f"2  read {n} records in {time.perf_counter() - began:.2f}s; other task ran {ticks - before} times meanwhile")
    t.cancel()
asyncio.run(two())

# 9: two producers of one class; a module reading what it publishes
class A(Module):
    name = "a"; inputs = (Tick,); outputs = (BodyResult,)
    def process(self, t): return Body(n=1)
class B(Module):
    name = "b"; inputs = (Tick,); outputs = (BodyResult,)
    def process(self, t): return Body(n=2)
class Echo(Module):
    name = "echo"; inputs = (BodyResult,); outputs = (BodyResult,)
    def process(self, r): return Body(n=r.result.n + 1)
for label, mods in (("two producers of BodyResult", (A, B)), ("a module that reads its own output", (A, Echo))):
    try:
        Pipeline("app", lambda: None, modules=mods, source_models=(Tick,)); print("9 ", label, "-> accepted")
    except Exception as e:
        print("9 ", label, "-> refused:", e)

# 13: an input without a timestamp
try:
    A().run(Tick()); print("13 ok")
except Exception as e:
    print("13 input without timestamp ->", type(e).__name__)

# 3: a join after a seek backwards
class Fast(DataModel):
    version: Literal["v1"] = "v1"
class Slowly(DataModel):
    version: Literal["v1"] = "v1"
j = Latest(trigger="fast", max_age={"slow": 10.0}).bound({"fast": Fast, "slow": Slowly})
j.feed(Slowly(timestamp=T0 + timedelta(seconds=58)))
b = j.feed(Fast(timestamp=T0 + timedelta(seconds=10)))
print("3  trigger at t=10s after a seek back, other input from t=58s ->", "bundled as fresh" if b else "skipped")
```

### Running it: the setups

A stack under its own project name and ports, so a developer's `p-swamp`
stack on :8000 is untouched:

```
docker build -t p-swamp:review .
docker run -d --name pswamp-review-bare -p 8131:8000 p-swamp:review     # bare, in-memory
docker compose -p pswamp-review -f docker-compose.yml -f compose.review.yml up -d --wait   # compose, :8132
SMOKETEST_URL=http://127.0.0.1:8132 uv run pswamp test smoke
(cd e2e && E2E_BASE_URL=http://127.0.0.1:8132 npx playwright test --reporter=list)
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

Below, `dc` is `docker compose -p pswamp-review -f docker-compose.yml -f compose.review.yml`.
Open the streamer at http://127.0.0.1:8132/pmu-test-streamer.

- **28**: `dc up -d --force-recreate --no-deps --wait kafka`, then reload the
  page and press play: nothing moves. `dc logs server | tail` shows the flood.
  `dc restart server module-worker batch-worker` recovers.
- **29**: the script below (in process, no stack).
- **30**: tick auto-pause and play: it pauses at the trip. `dc restart
  module-worker`, seek to 0 and play: no pause, and the box unticks itself.
  Tick it again, then `dc kill server && dc start server`, reload, play: the
  box is ticked and the excursion count goes on.
- **31**: `dc stop kafka`, press play (200), `dc start kafka`: it never plays.
- **32**: switch to `remote` and play; `docker pause
  pswamp-review-remote-data-stub-1`; seek, then switch to `sample`: the switch
  lands ~10 s later. `docker unpause` it afterwards.
- **34**: with the page open, `curl -X POST
  'localhost:8132/api/pmu-test-streamer/playback/seek?client_id=<id>' -H
  'content-type: application/json' -d '{"offset_s": 10, "end_offset_s": 5}'`:
  500.

In minikube: `uv run pswamp deploy minikube --no-browser --no-logs`, then
`kubectl port-forward service/p-swamp 30080:8000` and the page at
http://127.0.0.1:30080/pmu-test-streamer. A container is killed or paused
inside the node: `minikube ssh -- docker kill $(minikube ssh -- docker ps -q
--filter name=k8s_<container>_)`, `<container>` being `p-swamp`, `kafka` or
`remote-data-stub`.

- **28**: `kubectl delete pod -l app=p-swamp-kafka`, wait for the new pod,
  reload and press play: nothing moves; `kubectl get pods` shows every pod
  Ready. `kubectl rollout restart deploy/p-swamp deploy/p-swamp-module-worker
  deploy/p-swamp-batch-worker` recovers.
- **30**: as in compose, with `kubectl delete pod -l app=p-swamp-module-worker`
  for the worker restart and a kill of the `p-swamp` container for the crash.
- **31**: kill the `kafka` container and post speed, then play, at once.

Comment 29, run from the repo root with `.venv/bin/python`:

```python
import asyncio
from pswamp_core.pipeline import Pipeline, PipelineRun, start_live_runs
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.transport import InMemoryTransport
from pswamp_core.host import serve_hosts
from pswamp_core.util.time import utcnow
from pswamp_models.player import SwitchSourceCommand
from pswamp_modules.sample_replay import SampleReplay
from pswamp_modules.frame_stats import FrameStatsModule

FRAMES = list(SampleReplay().read())

class FlakyLive(SourceModule):
    name = "flaky-live"; kind = "live"
    async def aread(self, start=None, end=None):
        for n, frame in enumerate(FRAMES * 100):
            if n == 20:
                raise ConnectionError("the PMU connection dropped")
            await asyncio.sleep(0.05)
            yield frame.model_copy(update={"timestamp": utcnow()})

async def main():
    pipeline = Pipeline("t", lambda: SourceSet([SampleReplay("sample"), FlakyLive("live")]), modules=(FrameStatsModule,))
    transport = InMemoryTransport()
    hosts = asyncio.create_task(serve_hosts(pipeline.hosts(transport))); await asyncio.sleep(0)
    (live,) = await start_live_runs(pipeline, transport)
    await asyncio.sleep(2)
    print("29 shared live run:", live.router.status().error)
    client = PipelineRun("c1", pipeline, transport); await client.start()
    client.dispatch(SwitchSourceCommand(client_id="c1", source="live")); await asyncio.sleep(1.5)
    s = client.router.status()
    print(f"29 a client switching to live later: mode={s.mode} ended={s.ended} error={s.error} frame={client.frame is not None}")
    for run in (client, live): await run.stop()
    hosts.cancel()

asyncio.run(main())
```

Observed:

```
29 shared live run: live: ConnectionError: the PMU connection dropped
29 a client switching to live later: mode=live ended=False error=None frame=False
```
