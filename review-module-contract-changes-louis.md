# Review comments: module contract changes on `e2e-refactor-organisation-louis`

For Louis. Scope: the models package, the module API and join, one project per
module, TOML pipelines, sources as modules, and their docs (`deef05a` to
`dbf635b`).

How it was reviewed: `core/src/pswamp_core/`, the models bases and the six
projects under `modules/` were read in full; compose, k8s, the Dockerfile, the
docs and the generator were read against that code. Comments 1 to 4, 9 and 13
were reproduced with the script in the appendix. The test suites were not run
then; on 2026-10-14 the branch was run end to end (comments 28 to 39, under
"Running it"). Whether other developers can start on modules, CIM lookup and
remote data, and the decisions to make first, are under "Readiness for edge
work". How hard it is to lift the desktop WAMPAC apps into modules is
under "Lifting the desktop WAMPAC apps". Comment 40 came later, under "Found in the contract
pass".

Compose, k8s and the pipeline file agree with the code today, and the module
index in `modules/README.md` matches all six projects.

---

## By severity, at `dbf635b`

Every comment below, ranked. "Before" means it was already there at `069f88f`,
before this review's scope; "Louis" means it came with `f70d7d6` to `dbf635b`.
Comment 39 is about the refused-socket change (`924221e`), not Louis's commits,
and is left out. "Decision" names the decision below that settles a comment;
"—" is a fix that needs no decision (step 5 under "Order"). Retested at
`16f36a5`: all still present except 23 to 27, which are fixed (see "Retest at
`16f36a5`").

**High**: breaks a running deployment, or silently loses what a user asked for.

| # | Issue | Origin | Decision |
|---|---|---|---|
| 28 | Kafka losing its topics stops the stack until every process restarts; probes stay green (recovery fixed 2026-10-14; probes open) | before | — |
| 29 | A live source that fails stays failed; later viewers are not told (fixed 2026-10-14) | before | — |
| 31 | A command sent during a broker outage is acknowledged, then lost or applied late (fixed 2026-10-14) | before | — |
| 30 | Module state belongs to the key: settings lost on a worker restart, inherited after a crash | before | D1 |

**Medium**: wrong in situations the project will soon reach, or a trap in the
module contract for the next module.

| # | Issue | Origin | Decision |
|---|---|---|---|
| 32 | A hung remote data service holds up every command of the run (fixed 2026-10-14) | before | — |
| 40 | A module command sent while following the shared live run reaches an instance that gets no frames (fixed 2026-10-14) | before | Decided |
| 1 | A `blocking` module runs `process` and `handle` in two threads at once (fixed 2026-10-14) | Louis | D5 |
| 2 | A sync `read` source holds the event loop; a live one would freeze the server (fixed 2026-10-14) | Louis | — |
| 11 | A module with a dependency of its own fails to import in the image | Louis | D4 |
| 33 | The models layering test fails, so the unit tests are red (fixed 2026-10-14) | Louis | — |
| 6 | No teardown hook: a resource leaks per evicted key | before | D1 |
| 9 | Two producers of one class, or a cycle, pass every check | before | D14 |
| 5 | A module cannot publish outside a call | Louis | D2 |
| 3 | The join builds its bundle at dequeue; an input from after a seek back stays fresh | Louis | D1, D5 |
| 4 | `class X(SourceModule, Playable)` is accepted and half works | Louis | — |
| 14 | Several `@on` inputs share one drop-oldest queue | Louis | D5 |
| 18 | A non-playable history is pumped unpaced; the generator writes that shape | Louis | — |
| 10 | One flat namespace for source settings; modules cannot be configured | Louis | D3 |
| 21 | A generated source's pipeline file is loaded by nothing | Louis | — |
| 20 | The remote-data stub is in the image by an unchecked `.dockerignore` exception | Louis | — |

**Low**: edge cases, small leaks, tooling.

| # | Issue | Origin | Decision |
|---|---|---|---|
| 38 | A run keeps playing for 300 s after its last socket closes | before | — |
| 36 | An outbox reports falling behind, never catching up | before | — |
| 34 | A seek whose end is not after its start answers 500 | before | — |
| 35 | A huge negative step reaches the tray as `OverflowError` | before | — |
| 13 | An input without a `timestamp` fails every body result | before | — |
| 15 | `missing="skip"` skips silently | Louis | — |
| 8 | "A source is a module" holds for the type, not the behaviour | Louis | — |
| 7 | A source's outputs past the first are half supported | Louis | — |
| 37 | The error tray keeps 20 notices per client id for ever | before | — |
| 12 | Code shared by two modules has no home | Louis | D4 |
| 19 | Three rules AGENTS.md calls test-enforced are not | Louis | D7 (part) |
| 22 | The generator's worker-list patterns are not bounded to their block | Louis | — |
| 16 | `SourceConformance` reads without `open()` | Louis | — |
| 17 | `Module` has no `abstract = True` | Louis | — |

**Docs and wording**: 23 to 27 (Louis). Fixed in `16f36a5`; see the note under
"Docs and wording".

---

## Readiness for edge work, and the contract pass (2026-10-14)

The question: can other developers start on modules, CIM lookup and remote
data integration while the pipeline, transport and the rest of the plumbing
keep changing under them?

**The split is right.** A module declares inputs and outputs and writes plain
code; a source writes `read` or `aread`; neither sees the transport, runs,
hosts or the broker. Edge code today imports `Module`, `SourceModule`,
`Playable`, `EnvSetting`, `TimeRange`, `SourceConformance`, `CommandRefused`,
three time helpers and `pswamp_models`, nothing else. Comments 28, 29, 31, 32,
1, 2 and 14 can be fixed behind that line, with no module or source changing.
Messages leave pydantic's default (unknown fields ignored), so an optional
field added within `v1` does not break an older reader.

**What is not settled is what edge code is written against.** Deciding those
later changes edge code, so they are decided first (the decisions below), then
the edges open.

### Readiness

| Plug point | Ready? | Waits for |
|---|---|---|
| Remote data integration | Now. The integration is the HTTP contract (`doc/remote-data-integration-contract.md`): a deployment's service never touches the core. | D3 (settings names, before deployments are configured); D13 later |
| CIM lookup | After D8 to D11. | Only D8 and D10 need code, both small |
| Modules, per-frame | Now. | |
| Modules, stateful, periodic, configured, or with dependencies | After D1 to D5. | |

### The CIM scope (decided 2026-10-14)

A CIM plugin is a clean place to add CIM lookup logic later. Its outcome is a
reference id on the frame, not grid data on the transport. The hook exists:
`CimReferenceEnricher.reference_for(header)` (`core/src/pswamp_core/enrich.py`),
called once per channel layout, cached, stamped on every frame as
`PmuHeader.cimReferenceId`, applied to every source stream in every process
that builds a `SourceSet`. Today it returns the configured stub id.

### Decisions

Each: the question, the options, a recommendation. Nothing is built until they
are decided.

**D1. When a module instance starts and stops.** Settles comments 30, 3(b)
and 6. Today
an instance belongs to the client id (`host.py:251-261`): it survives seeks and
switches, a worker restart drops it silently, and a new run inherits it after a
crash. No teardown. Options: (a) an instance per run: the run's transport key
carries a run id, so a new run always gets fresh instances; (b) keep the client
id, and the run announces its start so a host rebuilds; (c) as now, documented.
Recommend (a), plus a `teardown()` hook, a `reset(reason)` hook called on seek
and source switch (default: nothing), and **sticky settings**: a command class
marked `sticky` is replayed by the run to a rebuilt instance, so a user's
setting (auto-pause) survives a worker restart. Touches: every stateful module.

**D2. Output outside a call.** Settles comment 5. Options: (a) a periodic hook:
`every = 1.0` and `tick(now)`, returning outputs like `process` does; (b) an
injected `publish` (the `setup(out)` that was removed); (c) none, documented.
Recommend (a): it keeps "return, don't emit" and covers watchdogs, periodic
summaries and windowed analyses (buffer in `process`, compute in `tick`). Open
within (a): whether `tick` may run in a thread while `process` keeps reading.

**D3. Configuration.** Settles comment 10. Today module settings are constants, the
pipeline file forbids settings, and sources read `{NAME}_{SETTING}` in one
namespace across apps (`REMOTE_URL`, `LIVE_PATH`). Options: (a) one style for
modules and sources: declared settings, values in the pipeline file
(`[modules.<name>]`, `[sources.<name>]`), app-scoped environment overrides
(`<APP>_<NAME>_<SETTING>`, beside the existing `<APP>_SOURCES`); (b) environment
only, app-scoped. Recommend (a), now: it renames every deployed setting, so it
lands before remote-data teams configure deployments. A module listed twice
under two names follows from it.

**D4. Dependencies and shared code.** Settles comments 11 and 12. The image gets a
module's third-party dependencies only through the server's manifest, which the
generator edits; a module added by hand ships without them. Recommend: a
`pswamp check` step that every `modules/*` project is a server dependency; and a
home for shared code, `libs/<name>/` projects that modules may depend on (the
layering test allows module → lib, never module → module).

**D5. Guarantees, and what is experimental.** Settles comment 1, and parks 3
and 14 until they are fixed (step 4). Recommend:
guarantee one call at a time per instance (a per-instance lock in the host;
internal); mark the join and several `@on` inputs experimental until 3 and 14
are fixed, in the docstring and the cookbook.

**D6. How messages change.** Settles no comment: it comes from the readiness
question and the remote contract's "Not settled yet". Recommend the rule: within a version, add
optional fields only; a breaking change is a new class or version, published
beside the old one during a move. Make "unknown fields ignored" explicit on
`DataModel` with a test, and have `pswamp check` flag a field removed or
changed in `pswamp_models` against a committed schema snapshot, as it does for
the api contract.

**D7. The public API.** Settles part of comment 19 (a module importing
another module gets caught). `pswamp_core/__init__.py` exports nothing. Recommend:
re-export the edge surface from `pswamp_core` (`Module`, `on`, `Latest`,
`SourceModule`, `Playable`, `EnvSetting`, `TimeRange`, `CommandRefused`,
`SourceConformance`, the time helpers, the CIM lookup base), call everything
else internal, and have the layering test hold module and source code to it.

**D8. Installing a CIM lookup.** From the CIM scope; settles no comment. Today `pipeline_config.py:203` hard-codes
`CimReferenceEnricher`; the pipeline file takes only `cim_reference`.
Recommend: `[enrich] cim = "<entry point>"` in a `pswamp.enrichers` group,
configured as in D3; `cim_reference` stays as the stub's setting.

**D9. What a lookup receives.** From the CIM scope; settles no comment. Today the layout only: no stream (`mRID`), no
source name, no time, so a recording from before a grid change cannot get the
old model's id. Recommend a small frozen context object (header, stream
`mRID`, source name, the first frame's timestamp), so it can grow without
breaking a lookup.

**D10. I/O and failure.** From the CIM scope; settles no comment. Today it is synchronous on the event loop ("no
I/O"), and a lookup that raises stops the stream. Recommend: an async form,
awaited once per new layout before its first frame goes out, plus `open` /
`aopen` for loading at start (as sources have); a failed lookup passes the
frame with no id and reports once per layout on the error tray.

**D11. How long an id holds.** From the CIM scope; settles no comment. Today per layout, for the life of the run.
Recommend: cache per (layout, stream); a lookup may return a validity end,
after which the next frame triggers a new lookup.

**D12. One id per layout or per column.** From the CIM scope; settles no
comment, only a doc mismatch on `cimReferenceId`. Recommend one per layout now. Under
D6 a per-column list is an optional field added later without breaking anyone.
Also settle the doc mismatch: a source may carry its own id (a recording made
with one); the lookup fills it when absent, which is what the code does.

**D13. Remote data, later.** Settles no comment: it is the remote contract's
own "Not settled yet" list. Authentication and TLS, limits, and models beyond
`pmu.frame` stay in the contract's "Not settled yet". Recommend naming the
settings now (`<APP>_REMOTE_TOKEN`, a CA bundle) under D3, so adding them is
additive. Live data over a remote service is a second contract, not this one.

**D14. One class, several producers.** Settles comment 9 (two producers of
one class). Comment 9 suggests refusing them. The WAMPAC apps need the
opposite for events: every app reports a status, several raise alarms, each
onto one topic that one consumer reads (`AlarmSender` in
`desktop/src/pswamp/coordination/alarm_handling.py` does exactly that). Options:
(a) refuse, and give each app status and alarm classes of its own; (b) allow
several producers for a class marked as an event stream (status, alarms),
refuse it for anything else; (c) allow it everywhere, as now. Recommend (b);
a cycle stays refused either way. Note `run.latest` keeps only the newest
message of a class, so a page showing a stream needs a store at the edge, as
the grid monitor's `AlarmStore` is today.

### Decided (2026-10-14)

- **What "sound" takes.** Six comments are design faults, not code faults,
  and are fixed first: 30 with 3(b), 6 and 40 (D1: the transport key names a
  client, not a run); 31 and 32 (an acknowledged command can vanish); 28 (a
  broken broker leaves the probes green); 1 (D5's per-instance lock); 2; 29.
  Then D7, D3, D2, D14 and D4, one at a time. Deferred: D6 (write the
  additive-only rule down for now), D8 to D13 (until CIM work starts), the
  join and several `@on` inputs (3(a) and 14: experimental, per D5), and every
  Low comment.
- **Comment 40: refuse.** A module command sent while following a shared live
  run answers 409. Module settings apply only to a client's own replay. As
  built, only a module that reads the stream is refused. A module with no
  inputs (the range summary) reads its own sources, so its instance under the
  client's key is the right one, and it still answers.
- **Comment 31: retry, then report.** An outbox retries a command until a
  deadline (~10 s). If it gives up, the server reports to that client's tray
  in process, not over the transport. Command topics resume from their last
  position after a consumer reconnect; data topics still start at the end.

This replaces "Order" below, which is kept for the record. The new order: 33;
1; 2; 40; D1 (30, 3(b), 6); 31 and 32; 28; 29; then the five decisions.

### Order

1. Decide D1 to D14.
2. Build the decisions that change edge code: D7, D3, D1, D2, D8 to D10, D4,
   D6, D5.
3. Open the edges: remote data now; CIM lookup after D8 to D11; modules after
   D1 to D5.
4. Any time, behind the line: 28, 29, 31, 32, 2, 14, 3.
5. Fixes that need no decision, any time: 33 first (it keeps the unit tests
   red), then 4, 7, 8, 13, 15, 16, 17, 18, 20, 21, 22, 34, 35, 36, 37, 38, 39,
   and the two rules of 19 that D7 leaves.

---

## Lifting the desktop WAMPAC apps into modules (2026-10-14)

How hard it is to move the monitoring applications in
`desktop/src/pswamp/monitoring/` into `modules/` under today's contract.

**What there is.** Five files, 70 to 190 lines each, on shared templates
(`app_templates/`: `SnapshotApp`, `TimeWindowApp`, status reporting and
`AlarmHandler`), labeled time windows (`utils/`), a C37.118 decoder
(`utils/pypmu.py`), Kafka/MQTT I/O (`streaming/`) and alarm handling
(`coordination/`): ~2,100 lines in all. The analysis inside each app is a
small numpy function; the rest is a run loop, I/O and windowing that the core
now does.

**Spike.** Islanding and line outage written as `Module`s (scratch, not in the
repo), calling the desktop algorithms unchanged, run as a script over the
grid monitor's N44 recording (3,501 frames, 700 columns, 40 KB per frame as
JSON):

- Islanding: islands 6500, 6700, 6701 from t=23 s (the grid monitor's sanity
  values); 0.03 ms per frame. After the reconnection (41 to 52 s)
  `detect_islands` returns overlapping groups; the web layer fixes that up
  today (`island_groups` in `pswamp_web/stores.py`), so a port moves the fix
  into the module.
- Line outage: disconnect at 20.2 s, connect at 40.0 s; 0.02 ms per frame.
- Each is ~40 lines, plus a ~40-line window over a frame's columns that both
  need.
- N4SID, timed separately on a 45 s window of the 44 frequencies: 0.21 s per
  identification on this Mac (0.26 s with one BLAS thread; an earlier
  container measurement was 0.62 s). The least damped modes come out at
  0.019, below the app's 0.03 "Emergency".

| App | Port | Why |
|---|---|---|
| Islanding (`islanding.py`) | Easy | Pure function; evaluating on data time (1 Hz over a 10 s window) fits `process` as is. Move in the overlapping-groups fix; alarms per D14. |
| Line outage (`line_outage_detection.py`) | Easy | Threshold over 10 samples, with state. Needs current channels, which no source in `modules/` has (below). |
| N4SID mode estimation (`n4sid.py`) | Medium to hard | `blocking = True`, and while an identification runs the instance reads nothing: at 1x the queue (64 frames) covers it, faster replays drop frames, and the window gets gaps N4SID does not expect (D2's open question). One identification per second per client watching a replay. `nfoursid` brings pandas and matplotlib (D4). Its `warnings.simplefilter("error", ...)` at import changes every module in the worker. Eigenvalues and mode shapes are complex: they need a wire shape. Without `window_length` its window grows for ever. |
| FFT (`fft.py`) | Medium: design, not code | Publishes nothing: the Qt plot reads its spectra off the app object. Its output (a spectrum per channel per evaluation) needs a message designed. Its constructor talks to Kafka directly; that goes. Its thresholds say "need to be adjusted". |
| FFT v2 (`fft_v2.py`) | Not portable | Imports `monitoring/utils.py`, deleted on 2026-03-03 ("Removed unused TimeWindowRTApp"). Dead code. |
| Voltage stability, SSI, Prony | Not here | The examples and the app launcher import them; they were never in this repo. |
| Status and alarms (`AlarmHandler`, `AlarmSender`, `ReportingApp`) | Medium: contract | Each app's status (OK, Alert, Emergency) feeds one alarm consumer: several producers of one class (D14). Status once a second when nothing else is published needs D2's tick. |

**Work shared by all of them, done once:**

1. A window over a frame's columns (by measurement, NaN handling, a new
   layout resets it). The desktop's `TimeWindowLabeled` and `PMUDecoder` work
   on C37.118 frames and live in the desktop package, which a module may not
   import, so it needs a home (D4's `libs/`).
2. A source with the data. `sample-replay` holds 60 frames (3 s at 20 Hz,
   voltage and frequency only). Islanding needs 10 s, N4SID 45 s, line outage
   currents. A source over `n44_line_trip_50hz.npz` (70 s, 50 Hz, 700 columns)
   covers all three.
3. Result models in `pswamp_models`: islands as station names, events with
   stations, eigenvalues as pairs; today's results are dicts of numpy arrays
   and uuids.
4. A window reset on seek and source switch (D1's `reset`). Without it a seek
   back mixes the old window with the new stream.
5. The grid monitor's pages read the desktop apps today (`pswamp_web`, on
   threads). Modules help those pages only once they are re-pointed at them.

**Verdict.** The algorithms lift with little change, and the contract fits a
windowed, data-time-driven analysis. The cost is around them: the window
helper and its home (D4), a source with the data, D1's reset, D2 for N4SID
and status, D14 for alarms, an output design for FFT, then the pages.
Suggested order: islanding and line outage first (after D4 and the N44
source); status and alarms with D14; N4SID after D2 and D4; FFT once its
output is designed.

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
- Fixed 2026-10-14: `Module._calling`, held by `arun`, `arun_command` and
  the host's command path (`validate` and `ahandle` together). The appendix
  script now prints `overlapped = False | threads: 1`.

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
- Fixed 2026-10-14 as suggested, N being `YIELD_EVERY = 64`
  (`sources.py`). The appendix script now prints "other task ran 335 times"
  for the same read (0.46 s).

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
- Recovery fixed 2026-10-14. A failed publish forgets its topic, so the next
  try makes it again. The consumer checks every 2 s that the topics it holds
  exist (aiokafka only logs a lost one) and reopens if not. On assigning, it
  asks the broker which topics exist instead of trusting `_created`. The last
  was the actual wedge in compose: a consumer reopened on a connection error
  skipped making its topics, and its offset calls timed out every 40 s, for
  ever. Seen again (compose, Kafka recreated): ten fresh module results 0.9 s
  after play, 1 server log line in 5 s, CPU back to normal, no process
  restarted. Probes are still open: `/healthz` does not cover the broker
  (AGENTS.md says why), and the workers still have none.

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
- Fixed 2026-10-14 as suggested. The router's pump reopens a live feed that
  fails or ends, from now, after 1 s doubling to 30 s. An outage is reported
  once, and the feed counts as back at its next frame. A shared run puts its
  `PlayerStatus` on the transport and repeats it every 2 s while its feed is
  down. A follower keeps it apart from its own, and `PipelineRun.status()`
  (what the streamer page now reads) carries its error. The script below now
  prints `frame=True` for the late client.

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
- Partly fixed 2026-10-14 (as decided): an outbox retries a control message
  with backoff until `CONTROL_DEADLINE_S` (10 s) after it was queued, then
  gives it up and calls `on_undelivered`. One still queued at its deadline is
  given up unsent, so `play` is no longer applied 24 s after its 200. A run
  turns that into an `ErrorEvent` for `on_error`, and `shared.run_registry`
  hands it to the tray directly. Then: a reopened Kafka consumer resumes the
  control topics where it was (`_resume_at`), and a command carries its issue
  time (`Command.timestamp`). A `CommandInbox` refuses one issued more than
  10 s ago, through the tray, so a resumed backlog is reported, not applied.

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
- Fixed 2026-10-14 as suggested. `CommandInbox(preempt=...)`, which the run
  gives `SwitchSourceCommand`, reads ahead while a command is applied. A
  switch cancels the one in progress and supersedes those queued before it,
  each reported on the tray. Cancelling is safe here: a playable source runs
  its commands in its own task, which the switch stops anyway. The coverage
  timeout is `REMOTE_COVERAGE_TIMEOUT` (default 10 s).

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

### Retest after the fixes (2026-10-14)

At `9d40858` (the fixes for 33, 1, 2, 40, 31, 32, 28 and 29), in bare,
compose and minikube, with the scratch scripts of this pass (sockets for the
page and the tray, POSTs, docker or kubectl for the outages).

- Regression: `pswamp check` passes. `pswamp test server` gives 457 passed,
  45 skipped, plus 11 Kafka cases against a broker. `check-generators`
  passes. Smoke passes in all three setups. Playwright: 11 passed bare, 12
  compose, 12 minikube. Every route renders clean in headless Chromium and
  Firefox in all three, and the monitor opens 5 data sockets plus the tray's.
- 28: compose, Kafka recreated: ten fresh module results 0.9 s after play,
  0 server log lines in 5 s, no process restarted. Minikube, Kafka pod
  deleted: the same, 3.0 s after play, no pod restarted.
- 31: compose, Kafka stopped: play is reported on the tray at 10 s ("not
  delivered within 10 s, so it was not applied") and stays unapplied once
  the broker is back. Kafka paused for 3 s: the play is applied when it
  returns.
- 32: compose, the stub paused mid-replay, a seek, then a switch to sample:
  the switch lands 0.1 s after its POST (it was ~10 s). The seek is reported
  as stopped.
- 29, 1, 2: the appendix scripts now print `frame=True`,
  `overlapped = False` and "other task ran 335 times".

---

## Found in the contract pass (2026-10-14)

**40. A module command sent while following the shared live run reaches an instance that gets no frames.**
- Seen (in process, `SampleReplay` and `LiveSynthetic` as sources, the
  excursion module): a client switched to live follows `live.live`. An
  `AutoPauseCommand` from it builds an excursion instance under `c1`, and the
  host logs "excursion applied auto.pause". The live data and results are
  under `live.live`, so the setting changes nothing the client sees, and
  nothing says so.
- Where: `core/src/pswamp_core/pipeline.py:333-347`. `dispatch` publishes
  every command under the run's own key, following or not. A host builds an
  instance on any message for a key, a command included (`host.py:251-261`).
- Why: one case of D1. A module command is aimed at the client's run, but
  while following, the modules that matter run under the live run's key.
  Sending it there instead would change the setting for every viewer.
- Decided: refuse it with a 409 while following (see "Decided").
- Fixed 2026-10-14 in `PipelineRun.dispatch`: `CommandRefused` for a module
  with inputs while `_following` is set. The streamer's auto-pause box was
  already disabled while live; the Playwright spec now checks that.

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
