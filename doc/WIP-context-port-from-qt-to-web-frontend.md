# Porting p-SWAMP from Qt to a web front end

*This is the record/context of an LLM-assisted initial stab at porting the
[p-SWAMP](https://github.com/pswamp/p-SWAMP) library from Qt to a web front end. 
Keeping it around for now until we figure out if we want to continue down that road, or
if IFE+SINTEF want to start from scratch on a web frontend for the same data.*

How the grid monitor web port got built, what it cost, what is left, and where the Python
should live once it is done.

`AGENTS.md` describes the system as it *is*; this file is how it got there, why,
where the traps are, and what happens next. Read this if you are re-doing,
extending, or finishing the port, or deciding where the code lives.

**At a glance.** §1–§2: what exists and what was decided. §3–§6: the lessons (§4
is the expensive part). §7: the layout decision (plans in §8/§9). §10: the
roadmap for finishing the port and retiring Qt — read it *before* §7, it changes
the answer. §11–§12: backlog. §13: performance issues for a live feed.

---

## 0. Status: this happened in two moves

**Originally done in a separate repo.** The client-server harness lived in
`pswamp-client-server-poc` beside a `../p-SWAMP` checkout, and modified that
checkout *not at all* — p-SWAMP was a library reached through a uv path
dependency.

**Now one repo** (this one): harness under `app/`, desktop package at the root,
port reapplied on top. The port is unchanged; only the seam moved:

| Then (separate repos) | Now (one repo) |
|---|---|
| `p-swamp = { path = "../../../p-SWAMP" }` | `p-swamp = { path = "../../" }` — the repo root |
| `scripts/vendor-pswamp.sh` staged a filtered copy into `.vendor/` | **Deleted.** Source is already in the build context; `.dockerignore` filters |
| Image mirrored a two-checkout `/workspace` | Image mirrors the one repo at `/workspace/p-SWAMP` |
| compose watched `../p-SWAMP/src` | compose watches root `src/` |
| CI path filters `app/**` | also `src/**` + root `pyproject.toml`, since root `src/` now ships |

The `/workspace` depth trick survives for the same reason as before (§4.1). The
"changes nothing upstream" rule is now a **design rule, not a filesystem fact** —
no separate upstream to protect, but it still holds in the code (`pswamp_web/`
imports `pswamp.*`; nothing under root `src/` imports from `app/`) and keeps
either §7 move cheap. Only review enforces it now.

---

## 1. What exists

**Server** — `app/server-python/src/pswamp_web/` (~2200 LOC): `wire.py` (schema
the Qt side never needed), `bus.py` (thread→loop), `hub.py` (one pipeline per
client + the registry), `replay.py` (source + counting-window subclass),
`recorded_io.py` (replay through p-SWAMP's `io` seam), `channels.py`,
`grid_model.py`, `stores.py`, `data/n44_line_trip_50hz.npz`, five page packages,
and `tools/record_n44_dataset.py` (regenerates the recording under `[full]`).

**Client** — `app/client-web/src/pages/grid-monitor/`: one app, six routes — the
main window at `/` plus five focused panel routes rendering the *same*
components at `variant="focused"`.

**Build** — image ~700 MB (scipy 119 + pandas 45 + numpy 56 dominate).

### Four things the harness needed that the core did not provide

| Need | Where |
|---|---|
| Replay a recorded, *labelled* PMU stream through the `io` seam | `pswamp_web/recorded_io.py` (~500 LOC) |
| A recorded Nordic 44 dataset with a real disturbance | `pswamp_web/data/n44_line_trip_50hz.npz` (4.9 MB, 700 channels), made by `tools/record_n44_dataset.py --channels all` |
| Samples-new-since-last-read (for delta pushes) | `CountingTimeWindowLabeled` in `replay.py` (~30-line subclass) |
| Disjoint island groups | `island_groups()` in `stores.py`, compensating a core bug |

The last two are **compensations, not improvements** — underlying gaps still in
`src/pswamp/`, listed §11. Don't "simplify" either away without fixing the gap.
The first two should arguably live in the core, and are written so they can move.

**`synchrophasor` is deliberately excluded from the image** — a base dependency,
but only the live-PMU and playback paths import it, and it's the one dep fetched
from git; excluding it keeps git, network and a hashless VCS pin out of the
build. The Dockerfile's `import server` smoke test makes that a checked decision.
§10.2 puts it back with the live PMU path.

### Cost to recreate, if thrown away

| | Cost |
|---|---|
| The recording `.npz` | **Cheap** (~7 s), but needs `[full]` + working `tops-rt` — only cheap while that env exists |
| `recorded_io.py` | **Expensive.** Not the code — the §4.3/§4.4 knowledge of what `TimeWindowApp` expects |
| `pswamp_web/` | Moderate. `wire.py` shapes and the `bus.py` bridge are the durable parts |
| The React client | Moderate — build it as one dashboard this time (§6) |
| **§4 of this doc** | Not recreatable except by paying for it again |

### The recording, and why it carries currents

`--channels all`: **3501 samples × 700 channels**, 4.9 MB (up from 176 channels /
1.0 MB). The extra 524 are `i_Magnitude`/`i_Angle`, for one reason —
`LineOutageDetectionApp` reads `i_Magnitude` and nothing else does; without them
it runs and detects nothing forever, worse than not running. Simulation is
otherwise identical (`verify()` proves it), and the time-window stream is bounded
by client channel selection, not recording width, so bandwidth is unchanged.

**Regenerating needs less than `[full]`:** a 3.11 venv with the root package +
`tops-rt` + `synchrophasor`, no Qt. Wart: the tool also needs `fastapi` on the
path, only because importing `pswamp_web.recorded_io` pulls in the whole web
stack. Worth fixing in the tool.

### Measured values, for sanity-checking a change

Re-verified against the running container after the repo merge:

- median frequency **50.0009 Hz**; median voltage **418.6 kV**
- islanded stations **6500, 6700, 6701**; island groups summing to exactly **44**
  with no overlap
- time-window steady state **5.85 KB/s** (vs ~1.4 MB/s naive); phasors 16.3 KB/s @ 5 Hz
- main window opens exactly **5** WebSockets (app status, time window,
  islanding, phasors, line outage); `e2e/grid-monitor.spec.ts` asserts it

---

## 2. The framing decisions, and whether they held

Five decisions taken before any code. Four held.

| Decision | Rationale | Verdict |
|---|---|---|
| **Depend on the core; don't vendor or rewrite** | Fold the layers together later, so forking is backwards | **Held, strengthened** — p-SWAMP modified not at all, zero algorithm code copied |
| **Write the server as if it lives at `src/pswamp/web/`** | The fold should be a move, not a second port | **Held.** Nothing in `pswamp_web/` imports the rest of the backend (§7) |
| **Keep the core's threads; bridge to the loop** | Rewriting the core's execution model is the tail wagging the dog | **Held.** Two crossing points, no locks, no execution code touched |
| **Recorded replay, no broker** | Reproducible disturbance, one process, `io` seam lets a broker drop back in | **Held** — §10.2 calls the bet in |
| **Four pages, one per app** | Mirrors the four server packages | **Wrong** (§6). Views of *one* timeline, belong on one screen. Cost: a full client refactor |

---

## 3. The order that actually worked

With §6's corrections folded in:

1. **Replay layer first, standalone.** `recorded_io.py` + counting window, proven
   with a *synthetic* recording driving the real `IslandingApp`. Highest-risk
   step — it proves a decoder you wrote satisfies `TimeWindowApp`'s undocumented
   expectations. Before any web code.
2. **Generate the recording.** Unblocks everything downstream; the generator
   self-asserts the scenario fires.
3. **Dependency + Docker wiring, no features** (so a build failure isn't confused
   with a code failure). Assert the negative: `import PySide6` must fail in the
   container. **Add CORS here** (§4.8).
4. **The bridge, cheapest payload.** `Hub` + `Bus` + status endpoint. Two apps
   reporting status at 1 Hz through the bus into a browser = architecture done,
   rest is content.
5. **Static endpoint** (`GET /api/grid/model`) — first non-WebSocket route.
6. **Dashboard, panels one at a time** — measurements, islanding + alarms,
   phasors, status. *Not* four pages (§6).
7. **Docs**, then §10, then §7.

---

## 4. Landmines

The expensive part. Each cost real time; none was predictable from the docs.

### 4.1 uv refuses to normalise a path above its base directory
Path dependency resolved on the host, failed in the image with *"cannot normalize
a relative path beyond the base directory"* — uv does **not** clamp at `/` like a
shell, so `/app/../../` → `/` was wrong. **Fix:** mirror the developer's
directory *depth* in the image — repo at `/workspace/p-SWAMP`, server at
`/workspace/p-SWAMP/app/server-python`, so `../../` is correct in both places.
This is why the image doesn't flatten the server to `/app`, and the biggest piece
of machinery §9 would delete.

### 4.2 `uv export` needs the path dependency to exist, even when excluding it
`--no-emit-package p-swamp` only suppresses it from the *output*; uv still
generates the package's metadata while resolving. **Fix:** copy only root
`pyproject.toml` + `README.md` first (uv reads the README because `readme =`
points at it — excluding it fails the build); copy source after the wheel
install, then `uv pip install --no-deps -e`.

### 4.3 `topsrt`'s interfacer deliberately drops samples
`InterfacerQueues.interface_fun` calls `output_stream.get_nowait()` before every
put — built to keep a *live* consumer on the newest data. A recorder attached this
way loses most of the stream and produces a gap-riddled recording that still looks
plausible. **Fix:** bypass the threaded interfacer — register a plain sync
function in `rts.interface_functions[...]` calling
`publisher.update(read_input_signal(rts))` inline. Result: exactly 3501 samples
for 70 s @ 50 Hz, no drops.

### 4.4 The time-window pre-fill overflows the reader queue
`TimeWindowApp.__init__` calls `seek_relative_input_offset(-n_samples)` — a burst
of 500 frames into a streaming-sized queue. Drop-oldest backpressure (correct for
a lagging live consumer) silently discarded 60% and logged a misleading "consumer
is behind". **Fix:** separate the paths — `_offer()` for live frames (drop
oldest), `_push_history()` for the deliberate burst (grow, never drop). Related:
start the app threads **before** the player, or first frames publish into queues
nobody drains.

### 4.5 `detect_islands` returns overlapping groups (core bug, compensated here)
`island_idx` was masked with `& ~assigned` but the returned `islands` list was
not, so a channel near two references appeared in both groups; consumers
recovering the main system by subtraction got far fewer stations than connected.
**Compensated in `island_groups()` (`stores.py`)** by claiming each channel for
the first group reporting it — 0 overlaps across 104 assessments, summing to 44.
Real fix is two lines in `detect_islands` (§11). Only visible because the port
*printed real island membership early* — do that.

### 4.6 NaN is not JSON, and it is the normal case
`json.dumps` emits bare `NaN`, which `JSON.parse` rejects. A `TimeWindow` is
all-NaN until it fills and the decoder NaNs missing frequencies — so this breaks
the **first message of every page**. **Fix:** `Sample = float | None`, a
`series()` helper, and one `send_state()` every page uses (`model_dump_json`,
never `send_json`).

### 4.7 Re-sending the window is ~1.4 MB/s per client
30 s × 50 Hz × 8 channels at 10 Hz. **Fix:** send the window once, then only new
samples (`mode: "full" | "append"`). 5.85 KB/s measured — a ~240× cut. The
difference between a page that works and one that does not.

### 4.8 CORS is invisible until the first HTTP fetch
WebSockets are exempt from the same-origin policy, so every socket worked in dev
across origins. The moment a panel used `fetch` (grid topology, channel
catalogue) the browser silently discarded the response — "Loading grid model…"
forever, dev only. **Fix:** `CORSMiddleware` in `server.py`, added with the
dependency wiring. (Nothing depends on it today; dev goes through the Vite proxy —
see `AGENTS.md`.)

### 4.9 A 50 Hz stream must not go through React state
Even holding samples in a ref, `setState` merely to *signal* a redraw runs a
render pass 10×/s producing no DOM change. **Fix:** `useServerSocket`'s
`onMessage` bypasses state — the hook writes a ref and notifies subscribers,
uPlot's `setData` runs outside React. Small SVG panels (phasors, islanding) use
plain state, correct for them.

### 4.10 This repo's eslint is stricter than it looks
`reactHooks.configs.flat.recommended` turns on compiler-backed rules as
**errors**:
- `react-refresh/only-export-components` (exempt only `components/ui/**`) — a
  module exporting a provider *and* its hook/context **fails the build**. Put
  contexts in a separate `.ts`.
- `react-hooks/set-state-in-effect` — no `setState` in an effect body.
- `react-hooks/refs` — no ref writes during render (update in an effect).

### 4.11 `NavLink to="/"` matches every route
react-router matches descendant paths unless `end` is passed. Once the index
page's path *is* `/`, the old `isIndex` workaround is dead code and every nav link
renders active.

### 4.12 `--virtual-time-budget` lies about the network
Cost the most time, produced a **falsely reported regression**. Headless Chrome's
virtual time fast-forwards timers but **not real network I/O**, so the last
WebSocket is cut off mid-handshake, non-deterministically by machine load; raising
the budget doesn't help, which makes it look like a logic bug. **Measure real
network behaviour only with real wall-clock time:** launch detached, `sleep`,
inspect (§5).

---

## 5. Verification recipes that actually work

**Socket count (the dashboard one):** fresh container, load with *real* time,
count uvicorn accept lines.

```bash
docker run -d --name verify -p 8124:8000 p-swamp:latest && sleep 14
nohup chromium --headless=new --no-sandbox --user-data-dir=/tmp/x \
  http://127.0.0.1:8124/ >/dev/null 2>&1 &
sleep 10
docker logs verify | grep -oE 'WebSocket /api/[a-z-]+/ws' | sort | uniq -c
# expect exactly 5 — one per stream, however many views read each
```

Do **not** use `--dump-dom --virtual-time-budget` for this (§4.12); it's fine for
static DOM checks where nothing is awaited.

**Live DOM after real time** — launch chromium with `--remote-debugging-port`,
sleep, drive CDP `Runtime.evaluate` over the debugger WS. The grid view is a
canvas, so count its non-background pixels (`e2e/grid-monitor.spec.ts` does)
rather than DOM nodes. On an ARM Linux VM point at the inner binary
(`/snap/chromium/current/usr/lib/chromium-browser/chrome`), not the snap wrapper.

**Bandwidth:** raw websocket client, read first message, time a 10 s window of the
rest.

**Backend import graph, no Docker:** from `app/server-python/`,
`uv run --frozen python -c "import sys; sys.path.insert(0,'src'); import server"`.
Catches a broken dependency in seconds. The image runs the same check; keep both.

**Don't `git stash` for a baseline** — one nearly lost the work. Use
`git worktree add --detach /tmp/baseline HEAD`.

**Know the pre-existing test failures before touching the core.**
`tests/monitoring/test_islanding.py` (IndexError), `test_mock_case.py`,
`test_kafka.py`/`test_mqtt.py` (need brokers) already fail on a clean checkout;
the suite *hangs on exit* after passing (non-daemon PMU listener thread), so
`| tail` never flushes — write pytest output to a file. Some modules import things
that no longer exist (`pswamp.monitoring.voltage_stability` — §10.1), so a
collection error is not necessarily yours.

---

## 6. What I would do differently

**Build the dashboard first.** The single real mistake. Four routes were chosen to
mirror the four server packages, but panels are views of *one* server-side
timeline — and it was a *less* faithful port than a dashboard, since the Qt UI
(`gui/main_window.py`) is one `QMainWindow` with a central grid view and docks.
Client/server symmetry is real on the server, false on the client. Cost: a whole
refactor plus two bugs that only surfaced once panels were adjacent (island
colours at index 0; `NavLink` matching everything).

**Add CORS with the Docker wiring** (§4.8).

**Decide panel sizes against a real viewport early.** The dashboard is still
~1200 px tall — sized by arithmetic, not by looking.

**Expect one adapter per analytic app, and budget for it.** Result dicts carry
numpy arrays, `uuid.UUID` and `datetime` — never hand one to pydantic. Repeats for
every app (N4SID needs complex eigenvalues split into `{re, im}`).

**What went right and should be repeated:** proving the decoder against the real
`IslandingApp` with synthetic data *before* a real recording; a self-asserting
generator; the "no feature code" Docker step; the cheapest endpoint (status) to
prove the thread→loop bridge.

---

## 7. Consolidating the Python into one place

The repo holds one Python codebase split across two projects that already depend
on each other one way (web → desktop). Two moves would collapse the split; **they
point in opposite directions and are mutually exclusive.**

| | **A — everything under `src/`** | **B — everything under `app/server-python/`** |
|---|---|---|
| Move | `app/server-python/src/pswamp_web/` → `src/pswamp/web/` | root `src/pswamp/` → `app/server-python/src/pswamp/` |
| Result | One package `pswamp`, with `gui/`, `visualization/`, `web/` as adapters over one Qt-free core | One project under `app/`; the root becomes repo furniture |
| Manifests | Two, plus a `web` extra on the root one | One |
| Web client (`app/client-web/`) | Moves too, sibling of `src/` | Stays put |
| Effort | Small server-side (`git mv` + ~13 imports); client raises a real question | Moderate, gated on a lint decision (§9.3) |
| Deletes path-dep machinery (§9.1)? | No — inverts it | **Yes, all of it** |
| Plan | §8 | §9 |

**True either way, worth protecting:** `pswamp_web/` is self-contained — no module
imports the rest of the backend (only stdlib, fastapi, pydantic, numpy,
`pswamp.*`), every intra-package import relative. That makes both moves cheap and
is the one invariant a change must not break.

### Recommendation: decide §10 first

**Don't pick on tidiness. The answer follows from whether Qt is being retired.**

- **If Qt stays** (indefinitely, or as a supported second client), **A is right.**
  `src/pswamp/` is then genuinely shared infrastructure with `gui/` and `web/` as
  sibling adapters — the shape the port was written for. Putting the shared core
  inside one of its two consumers (B) is backwards.
- **If Qt is removed** (§10.5), **B is right, and much cheaper once Qt is gone.**
  Delete `gui/`+`visualization/` and "the core" and "the web backend's dependency"
  become the same thing — plus 78% of the lint debt that makes §9.3 hard vanishes
  (672 of 860 errors are in those two subpackages).

So: **§10 first, then §7.** Consolidating before the Qt decision risks doing the
move twice, in the more expensive wrong direction.

**If a decision is needed now and §10 is unresolved**, take the cheap variant
(§9.2): move the desktop project *whole* into `app/pswamp-desktop/`, keeping it
separate. `app/` means "all the code" without committing either way, at the cost
of one extra `git mv` later.

---

## 8. Plan A: consolidate under `src/pswamp/`

Fold the web layer in so `pswamp` has `gui/`, `visualization/`, `web/` as
siblings. **Right if Qt stays.**

### 8.1 The server move

```bash
git mv app/server-python/src/pswamp_web src/pswamp/web
```

Then fix **13 references in `server.py`** (`import pswamp_web.grid` →
`from pswamp.web import grid`, and the `SERVICES`/`APPS` entries). Nothing inside
the package changes — imports are all relative.

Three pieces should *not* stay under `web/`:

- `web/recorded_io.py` → `pswamp/streaming/recorded_io.py`, beside `kafka_io.py`.
  Independently valuable (broker-free replay for tests/CI), so it can land first
  and alone. Only import to fix: `web/hub.py`.
- `web/data/n44_line_trip_50hz.npz` → `test_utils/sample_datasets/n44/recordings/`,
  read via `importlib.resources` (copy `grid_model.py`'s pattern for
  `grid_database.db`).
- `tools/record_n44_dataset.py` → beside that dataset.

Then **delete, not move**, the two §1 compensations: `CountingTimeWindowLabeled`
becomes `n_appended` + `snapshot()` on `utils/time_window.py`, and the
disjoint-group loop becomes the one-expression fix in `detect_islands`. Both in
§11 anyway.

### 8.2 Dependencies

Root `pyproject.toml` gains a **`web` extra** (`fastapi`, `uvicorn[standard]`),
not base deps — the core must stay importable without a web stack (same reason
`synchrophasor` is kept out of the image). `app/server-python/pyproject.toml` +
lockfile go away; the server installs as `p-swamp[web]`.

**Check the image doesn't gain Qt.** With one manifest, `[full]` and `[web]` are
siblings and the Dockerfile must install only the latter. The `import server`
smoke test + an explicit `import PySide6` *failure* assertion keep that honest —
keep both.

### 8.3 The web client

`app/client-web/` becomes a sibling of `src/` (e.g. `web-client/`), `vite build`
output copied to `pswamp/web/static/`. The Dockerfile's two-stage build moves
as-is. Genuinely open — **whether the package wants npm in its build at all**:

- **Yes**: Dockerfile unchanged, a source checkout needs node. Simplest, today's.
- **No, ship built assets**: commit `static/` or publish it as a release artifact
  (`AGENTS.md` currently says `static/` is never committed).
- **No, publish the client separately**: two artifacts, two cadences.

### 8.4 What this does not fix

The §9.1 path-dependency machinery doesn't go away — it inverts. The server still
points at a project it lives beside, the image still needs both trees, and
`error_check.sh`'s `app/`-scoped gate now covers *less* Python (`pswamp_web/`
leaves `app/`). That last is a real regression; rescope the gate in the same
change.

---

## 9. Plan B: consolidate under `app/server-python/`

Fold the core into the server project. **Right if Qt is being retired.** A plan,
not a decision — nothing here is done.

### 9.1 Why it is on the table

`AGENTS.md` used to say the two projects shared nothing. The grid monitor ended
that: the web backend declares `p-swamp` as an editable path dependency on
`../../`, `pswamp_web/` imports `pswamp.*`, root `src/` ships **in the image**,
and `app/server-python/uv.lock` already resolves the desktop package's whole
closure alongside FastAPI's. So they're coupled; what remains is machinery
spanning a gap that no longer needs spanning:

| Machinery | Exists because |
|---|---|
| `[tool.uv.sources] p-swamp = { path = "../../" }` | the packages are in different projects |
| The `/workspace/p-SWAMP` depth trick (§4.1) | uv won't normalise `../../` above its base dir |
| `--no-emit-package p-swamp` in `uv export` (§4.2) | the path dep must not be fetched from an index |
| A second `COPY` + `uv pip install --no-deps -e` layer | root `src/` installed separately |
| A second compose `watch` entry for root `src/` | ditto, for hot reload |
| `uv lock --upgrade-package p-swamp` as an extra step | plain `uv lock` won't re-read the path dep |
| Two lockfiles, only one read by any script | historical |

Consolidating deletes all of it — the case *for*. The case *against* is one
quantified cost, §9.3.

### 9.2 Target shape

```
app/server-python/
  pyproject.toml          # one manifest: fastapi + uvicorn + numpy/scipy/pandas…
  uv.lock                 # one lockfile
  .python-version
  src/
    server.py             # entrypoint, unchanged
    shared.py
    timeline/             # scaffold demo
    pmu_test_streamer/    # scaffold demo
    pswamp_web/           # the web layer  ── imports pswamp.*
    pswamp/               # ◄── moved here from root src/pswamp/
  tests/                  # ◄── moved here from root tests/
```

`examples/` is open (§9.6). `import pswamp` then resolves like `import timeline`
already does — off the working directory, `WORKDIR` being `src/`. No path
dependency, no editable install, no depth trick.

**The cheap variant / fence-sitter (§7):** move the desktop project *whole* —
`src/`, `tests/`, `examples/`, manifests — into `app/pswamp-desktop/`, keeping it
separate and keeping the path dep (`../pswamp-desktop`). `app/` means "all the
code" at a fraction of the risk (no manifest merge, no lint-gate question, no
packaging change), but deletes almost none of the machinery and commits to
neither §7 option.

### 9.3 The thing that actually decides this

**`scripts/error_check.sh` scopes every Python check by the literal dir `app`:**

```sh
find app -name '*.py' -not -path '*/__pycache__/*' -print0   # py_compile
ruff check --select E,F app
ruff format --check app
```

So the move silently drags desktop code under the gate. Measured on root `src/`:

| Check | Result |
|---|---|
| `py_compile` | **passes** (verified) |
| `ruff check --select E,F` | **860 errors** |
| `ruff format --check` | **119 of 149 files** would reformat |

Where the 860 live — the number tying §9 to §10:

| Subpackage | Files | Errors | |
|---|---|---|---|
| `gui/` | 52 | 477 | **Qt front end** |
| `visualization/` | 30 | 195 | **Qt front end** |
| `test_utils/` | 26 | 79 | |
| `utils/` | 11 | 33 | |
| `monitoring/` | 6 | 22 | the analysis core proper |
| `models/` | 5 | 20 | |
| `streaming/` | 7 | 12 | |
| `coordination/` | 3 | 11 | |
| `app_templates/` | 4 | 7 | |
| `styles/`, `database/` | 4 | 3 | |

**672 of 860 (78%) are in the two subpackages §10.5 deletes.** Retiring Qt cuts
this to 188 across 67 files — a weekend, not a project.

By rule: 508 `E501` line-too-long (cosmetic; `ruff format` doesn't fix long
strings/comments), 232 `F401` unused-import (auto-fix), 38 `F841` unused-variable
(auto-fix), 27+22 `F405`/`F403` star-import (real edits), 14 `F811` redefined
(read individually), **1 `F821` undefined-name (a genuine latent bug)**, 18
assorted `E` (trivial).

That `F821`:

```
src/pswamp/visualization/components/threshold_adjust.py:32
    self.range_slider = QRangeSlider(Qt.Horizontal)   # QRangeSlider never imported
```

`qtrangeslider` is a declared `[full]` dep, so this is a missing import raising
`NameError` whenever the widget is built. Nothing under `app/` reaches it — but it
means the desktop code has never been through even the loosest static check.

**Three ways to handle it, pick before starting:**

1. **Fix everything first.** Cleanest end state, worst diff — a `ruff format` over
   119 files destroys `git blame` and conflicts with anything in flight. Not
   recommended: turns a mechanical move into open-ended cleanup, 78% on
   maybe-deleted code.
2. **Exclude the moved tree, keep the gate as strict as today.**
   ```sh
   ruff check  --select E,F app --exclude app/server-python/src/pswamp
   ruff format --check      app --exclude app/server-python/src/pswamp
   ```
   Honest: root `src/` is ungated *now*, this preserves that. `py_compile` keeps
   covering everything, free. Verified `--exclude` applies to a subdir walked from
   a passed directory — but *not* to a path named on the command line (needs
   `--force-exclude`), so don't pass the package directly expecting the exclude to
   hold.
3. **Exclude, then ratchet.** As (2) but the exclude shrinks — clean a subpackage,
   drop it, it can't regress. Natural first targets are what the web stack depends
   on: `monitoring/` (22), `utils/` (33), `streaming/` (12) — 67 errors, not 860.

**Recommendation: (3), starting as (2).** Move with a blanket exclude so the move
reviews as a pure rename, then ratchet in separate commits. Fix the `F821` on its
own, immediately, as a bug.

### 9.4 Steps

Each should leave `error_check.sh` green and the container building.

**1. The `F821`, first and separate.** One-line import fix in
`threshold_adjust.py`; better reviewed as a bug fix than buried in a rename.

**2. Merge the manifests.** `app/server-python/pyproject.toml` absorbs the root
deps:

```toml
[project]
name = "p-swamp"                 # take the root project's identity
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.6,<0.116",
    "uvicorn[standard]>=0.34,<0.35",
    "numpy>=2.2.5", "scipy", "tomli", "pandas>=2.3.1",
    "numpy-dynamic-array", "pydantic>=2.12.5",
    "synchrophasor @ git+https://github.com/hallvar-h/pypmu",
]

[project.optional-dependencies]
full = [ ... ]                   # Qt/Kafka/tops-rt, verbatim from root
```

**`full` must stay an extra** — the only thing keeping PySide6 out of the image;
the Dockerfile installs no extras and its `import server` smoke test proves it.
Keep the smoke test. (If §10.5 has happened, most of `full` is deletable instead.)
Two flags come off the `uv export` line: `--no-emit-package p-swamp` and,
depending on step 3, `--no-emit-project`. `--no-emit-package synchrophasor`
**stays**, unless §10.2 restored the live PMU path.

**3. Decide packaging — `[tool.uv] package = false` stops being harmless.** Under
that flag, a moved-in `pswamp` **isn't installed anywhere**. The server is fine
(`import pswamp` off `WORKDIR`), but **`tests/` breaks** (imports `pswamp.*`, no
`conftest.py` path setup) and **`pip install -e .[full]` in `README.md` breaks**.
So make the project packaged, module root at the moved package:

```toml
[build-system]
requires = ["uv_build"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "pswamp"
# module-root defaults to "src"
```

A genuine hybrid to document in `AGENTS.md`: `src/` becomes *both* a packaging
layout (for `pswamp`) *and* a plain source folder (for `server.py`, `timeline/`,
`pmu_test_streamer/`, `pswamp_web/`, which resolve off `WORKDIR`). It reverses a
convention that file states flatly, so write it down or the next reader "fixes"
it. The image still need not install the project — `--no-emit-project` stays.

**4. The move.**

```sh
git mv src/pswamp app/server-python/src/pswamp
git mv tests      app/server-python/tests
git rm  uv.lock                       # nothing reads it
# root pyproject.toml: delete, or reduce to repo-level tool config only
(cd app/server-python && uv lock)
```

`git mv` keeps `git log --follow`. Nothing inside the package needs editing —
imports are absolute (`from pswamp.x import y`), and data files resolve two ways
that both survive: shapefiles + `default_config.toml` via `Path(__file__).parent`,
`grid_database.db` via `importlib.resources.files("pswamp.test_utils…")`, which
needs `pswamp` importable and nothing more. Verified.

**5. Unwind the machinery.** Delete in order, checking the build after each:
`[tool.uv.sources]` + the `p-swamp` entry; the Dockerfile's
`COPY pyproject.toml README.md`, `COPY src/` and `uv pip install --no-deps -e`
layers (collapse into the existing `COPY app/server-python/src/ ./src/`); the
`REPO_DIR`/`SERVER_DIR` ARGs + workspace-depth comment (`WORKDIR` back to `/app`,
`/app/src`); the root-`src/` compose `watch` entry; `.dockerignore`'s repo-root
block + its keep-these note; CI path filters `src/**` and root `pyproject.toml`
(build context can narrow again). Each has an explanatory comment — delete it with
the code, then grep `workspace`, `path dependency`, `--no-emit-package` for prose
that outlived it.

**6. Update the gate.** Add the §9.3 ruff excludes with a comment stating plainly
the excluded tree is **not** checked, and why.

**7. Update the docs.** `AGENTS.md` — "Two Python projects" becomes one project
with two dependency tiers, the `src/` ambiguity note goes (a real win), the
image-mirrors-repo-root note reverts, the packaging hybrid gets written down.
`README.md` — `pip install -e .[full]` runs from `app/server-python/`. This file —
§8 restated as "`pswamp_web/` → `src/pswamp/web/` *within* `app/server-python/`".
`doc/client-server-rig.md` — check for stale layout claims.

### 9.5 What this does not touch

The wire protocol, the client, the k8s manifests, runtime behaviour. If any
change, something went wrong — consolidation should be observable only as a
shorter Dockerfile and a smaller `AGENTS.md`.

### 9.6 Decisions still to make

- **Where `examples/` goes.** 13 MB, imported by nothing in `app/`, image-excluded.
  Under `app/server-python/` = research material inside a deployable for no
  benefit; at the root = half-consolidated. A third option: keep it at the root as
  repo-wide *documentation* (arguably what it is). Decide explicitly.
- **Whether the repo keeps a root `pyproject.toml`.** After the move it has no deps
  and builds nothing — could hold repo-level tool config, or be deleted.
- **Wheel packaging of data files is untested** (true of A too). Every install has
  been editable; nothing verifies `uv_build` includes `grid_database.db`,
  shapefiles, `sld.dxf`, `default_config.toml`, `n44_line_trip_50hz.npz`. Build a
  real wheel and load one — *before* the move if it changes step 3.
- **Whether `tests/` runs in CI once under `app/`.** Not run anywhere today; the
  move makes the omission conspicuous, and 4 of 17 modules are known-failing / need
  brokers (§5), so switching them on is its own work.

---

## 10. Completing the port, and retiring the Qt front end

Today is a **vertical slice**: one data source, one analytic app, four panels. It
proves the architecture but does not yet replace `gui/main_window.py`.

### 10.1 The gap, feature by feature

Qt is one `QMainWindow` — central grid view, docks (Apps launcher, Frequency,
Status, Alarms, Alarm details). Against that:

| Qt | Web today | Gap |
|---|---|---|
| Main window layout (`main_window.py`) | `GridMonitorPage` | **Done.** Grid view central, dock column on the right, alarm details in a dock beneath the grid. Docks do not float, close or re-tab |
| Grid view 3D, base layers (`dim_3d`: countries, lines, buses, bus names) | `grid-view/` — 2D canvas with its own projection | **Done.** Orbit, pan, zoom, per-layer toggles. No WebGL was needed: the layers are polylines and text |
| Grid view 2D (`dim_2d`) | `grid-view/`, 2D mode | **Done** for the same base layers |
| Grid view, several views as tabs (`GridViewContainer`) | 3D/2D switch on one view | Partial. One view, no named tabs |
| Single-line diagram, `geo` (`single_line_diagram`, DXF) | `GridModel.diagram`, from `tools/build_n44_grid_geometry.py` | **Done**, converted ahead of time into a committed fixture rather than at request time |
| Single-line diagram, `other` (schematic `sld.dxf`) | — | Missing. The tool converts only the `geo` diagram |
| Grid layers: voltage phasors, dynamic lines by frequency (`dim_3d/layers`) | — | Missing |
| Grid surfaces (`surface_plot`, heatmap layers) | — | **Missing.** These are filled surfaces, so they would need WebGL |
| Frequency plot (`FreqPlot`) | `FrequencyPanel` | **Done.** Every station's frequency, one colour |
| Time window plot (`time_window_plot*`) | `MeasurementsPanel` at `/time-window` | Done |
| App status (`AppStatusMonitoringWidget`) | `AppStatusPanel` | Done. No Stop / Open console: both need a command topic |
| Alarm overview (`AlarmOverview`) | `AlarmsPanel` + `AlarmTable` | **Done.** Click a row for detail |
| Alarm details (`AlarmHandlingDialogue`) | `AlarmDetailsDock` | **Done.** Info, event log, ack/annotate/silence, beside the alarm's view |
| Alarm view: islanding (`IslandingAlarmView`) | `AlarmView` + the grid view | **Partial.** Frequencies and phasors coloured by island, alarm start/end marked; the grid shows the island colours, the lift and the red branches all the time rather than only while an alarm is open. **No time slider**: it shows the live 30 s window, not a stored history of the alarm. Connectable lines are not marked green |
| Alarm view: oscillations | — | **Missing.** Needs `n4sid`/`fft` in the hub |
| Alarm view: voltage stability | — | **Missing**, see below |
| Phasor plot 2D (`phasor_plot`) | `PhasorDial` | Done |
| Line outages grid layer (`dim_3d/layers/line_outages`) | red branches in the grid view | Done |
| Phasor plot 3D (`phasor_plot_3d`) | — | Missing |
| Frequency heatmap (grid-view layer + launcher) | — | Missing. **The live one** |
| Voltage heatmap | — | **Dead in Qt** (launcher button commented out). Do not port |
| Channel select/tree | `ChannelPicker` | Done |
| Line outage detection | `LineOutagePanel` | **Done**, once the recording gained currents |
| App launcher (start/stop apps) | `AppsPanel` | **Partial.** Opens an application's view; starting and stopping is still the hub's decision |
| Multi-TSO alarm docks (`other_tso`) | — | Missing |

**`IslandingApp` and `LineOutageDetectionApp` are wired in.** `monitoring/` also
holds `n4sid` and `fft`, neither web-reachable yet. Each is "one adapter + one
panel" (§6) — established shape, repetitive not hard:

- **`N4SIDApp` slots straight in** — plain `TimeWindowApp`, no broker coupling,
  `run_analysis` returns eigenvalues + mode shapes. Cost: `nfoursid` pulls
  **matplotlib** into the headless image.
- **`FFTOnline` does not** — `__init__` calls `get_last_message_from_topic` and
  `consumer_seek_relative_offset` (Kafka-only, before any window exists). The
  algorithm (`calculate_fft_spectrum`) is a pure function and the part to reuse.

**Only port what Qt actually runs.** Voltage heatmap, SSI, Prony, "Time window
plot V1.5" buttons are commented out in `app_launcher.py`; `monitoring/fft_v2.py`
is dead (§11). Check `gui/main_window.py` + `gui/app_launcher.py` first. Two traps:

- **Voltage stability is half-missing.** Presentation exists
  (`gui/alarms/views/voltage_stability.py`,
  `gui/grid_view/dim_3d/layers/voltage_stability.py`,
  `visualization/voltage_stability_viz/dSdZ_plot.py`); the *analysis* half does
  not — tests import `pswamp.monitoring.voltage_stability`,
  `…voltage_stability_indicators.corsi_taranto`, and an example imports
  `pswamp.visualization.voltage_stability_old`, **none in the tree.** So it's
  "find or rewrite the analysis first", not "port a view". Scope that first.
- **`fft_v2.py` is dead** — port `fft.py`.
- **Line outage was blocked on data, not code**, now unblocked (needs
  `i_Magnitude`, §1).

### 10.2 The blocker that is not a feature: live data

The web stack replays a committed recording; Qt reads **live** data through
`pswamp/streaming/` (`kafka_io`, `mqtt_io`, `nqkafka_io`, `time_series_io`).
Nothing replaces Qt operationally until the web server does too.

**Designed for.** `hub.py` passes `io=self.player.subscribe(...)` into each app —
a constructor argument. Swapping in `kafka_io` is a one-line wiring change, the §2
bet. Don't let it become a rewrite. **The consequences are the hard part**, none
exercised by replay:

- **`synchrophasor` returns to the image** (§1), with git + a hashless VCS pin.
  Decide vendor / mirror / pin properly.
- **Replay controls stop making sense** — play/stop/seek are meaningless live.
  Make the source a *mode* (live | replay) with conditional controls, or split
  deployments. No dead buttons on an operational screen.
- **Reconnect, gaps, backfill become real** — a broker disconnects, and
  `TimeWindowApp`'s queue under a reconnect burst is the §4.4 landmine again.
- **`replicas: 1` stops being acceptable** — in-memory per-client state, sharper
  with per-client pipelines (five sockets on different pods = five unrelated
  replays). Horizontal scaling needs an external live store — a real design change.
  The single largest piece of unscoped work here.
- **Auth and CORS** — both wide open because every endpoint reads sample data.
  Neither is acceptable on real grid data.

**Keep the replay path when live lands** — it's the reproducible disturbance that
makes every panel testable and every §1 number meaningful. A mode, not a phase.

### 10.3 Suggested order

1. **Alarm details pane** — smallest useful step, existing machinery.
2. **One more analytic app end to end** — `line_outage_detection` or `fft`,
   whichever has the simpler result shape — proving "one adapter + one panel" is
   really the cost.
3. **The live `io` source** (§10.2) behind a mode flag, replay retained. Before
   the expensive visualisations — it decides whether any of this can be
   operational; learn that early.
4. **Remaining analytic apps** — `n4sid`/oscillations, voltage stability once its
   analysis half is found.
5. **Expensive visualisations** — single-line diagram (server-side DXF→GeoJSON),
   then 3D grid view (WebGL). *Done for the line layers, on a 2D canvas — see
   §10.1. What is left here is the surface and heatmap layers.*
6. **Operational work** — auth, and the external store that lets `replicas` > 1.

Steps 1–2 are worth doing regardless. Step 3 is the decision point.

### 10.4 What has to be true before Qt can be removed

A checklist, none currently true:

- [ ] Every panel an operator actually uses has a web equivalent — confirmed with
      operators, not inferred from §10.1.
- [ ] The web server reads live data (§10.2), reconnect tested against a real
      broker.
- [ ] Credible deployment: auth, and a defensible `replicas: 1` or the store that
      removes it.
- [ ] Single-line diagram and 3D view ported or explicitly dropped, decision
      recorded.
- [ ] `examples/` and `tests/` no longer depend on `gui/`/`visualization/`, or the
      deps are moved. Measured: **4 test modules and 18 example files** import
      them, and most of `examples/nordic44_rtsim/apps/` *is* Qt code. Most likely
      underestimated — and bears on §9.6's `examples/` question, since much of it
      would be deleted alongside `gui/` rather than moved.
- [ ] Anything else importing `pswamp.gui`/`pswamp.visualization` accounted for.
      Verified clean today: `monitoring/`, `coordination/`, `app_templates/` import
      neither. Re-check before deleting.

### 10.5 Removing it, and what that buys

Once the checklist holds:

```bash
git rm -r src/pswamp/gui src/pswamp/visualization
```

plus dropping `PySide6`, `pyqtgraph`, `pyopengl`, `qtrangeslider`, `ezdxf`,
`matplotlib` from `full` — at which point `full` may not be worth keeping as an
extra, and `kafka-python`/`nqkafka`/`tops-rt` can be reconsidered on their merits.
What it buys: **78% of the lint debt gone** (672/860 errors, 82/149 files — §9.3);
the `[full]` install stops needing Qt (headless becomes the normal case);
`src/pswamp/` becomes unambiguously "the analysis core" — the condition under
which §7 resolves to B.

**Do not delete early.** Qt is currently the only thing exercising several
analysis paths, and §10.1 was derived by reading it. It's the specification for
the remaining work; keep it until that work is done.

---

## 11. Changes to the analysis core deliberately not made

Real gaps the web layer works around locally. Each small, defensible on its own
merits, best proposed as its own change:

- **`detect_islands` returns overlapping groups** (§4.5). Two lines. Most clearly
  a bug.
- **`TimeWindow` has no monotonic append counter.** ~26 additive lines
  (`n_appended` + `snapshot()`), no behaviour change. Enables incremental updates
  (a socket delta here, an incremental Qt repaint later). Deletes
  `CountingTimeWindowLabeled`.
- **`QRangeSlider` undefined** in `visualization/components/threshold_adjust.py`
  (§9.3) — a missing import raising `NameError` when the widget is built.
- **`synchrophasor` is a base dep but only live-PMU/playback import it.** Moving it
  to `full` removes git, network and a hashless VCS pin from any headless install.
  (Worked around by image-excluding it; revisit under §10.2.)
- **`LineOutageDetectionApp` never reports a status** — `set_status()` is `pass`
  with the body commented out, so it keeps `SnapshotApp`'s initial `'Undefined'`
  for life while others move through `OK`/`Alert`/`Emergency` (verified over 30 s).
  The commented body is a copy-paste from islanding (tests
  `return_value['result']['islands']`, absent from line-outage results) — stubbed
  and never finished. **Deliberately not implemented here:** when an outage is
  `Alert` vs `Emergency` is a domain judgement belonging upstream. Qt shows the
  same `Undefined`, so the web client is faithful, not broken.
- **`monitoring/fft_v2.py` is dead** (no importers, superseded by `fft.py`, says so
  in its TODO); **two test modules carry a stray `from ensurepip import bootstrap`**
  breaking collection. Noticed in passing.
- **Three voltage-stability modules imported but absent** (§10.1):
  `monitoring.voltage_stability`, `…voltage_stability_indicators.corsi_taranto`,
  `visualization.voltage_stability_old`. Lost, or callers written against a plan.
  Resolve before scoping the voltage-stability port; makes the corresponding tests
  and example unrunnable today.

Further out:

- Split `coordination.AlarmMonitor` into a pure state machine + a Kafka feeder.
  `pswamp_web/stores.py` reimplements ~30 lines because the logic is trapped in a
  `for msg in consumer:` loop. Shapes match; §10.2 makes it necessary.
- Make `AlarmHandler` emit JSON-native types (`str(uuid)`, epoch float) instead of
  `uuid.UUID`/`datetime` — the root cause of `streaming/utils.encoder` pickling.
  A wire-format change for existing Kafka consumers; do it deliberately.
- Move `scipy` to an `[analysis]` extra (−119 MB of image).

---

## 12. Not done

- **Everything in §10** — the port is a vertical slice, not a replacement.
- **Either move in §7.**
- **Wheel packaging of the data files** (§9.6).
- **Tuning the main window against real viewports.** It fills the viewport
  from 1024 px wide up and stacks below that; checked at 1512×806 and 820 wide,
  not on a control-room wall or a phone.
- **The desktop test suite has never run in CI**, here or before the merge.

---

## 13. Performance issues to follow up (for a live feed)

**Only relevant if we keep iterating on the monitor frontend (as of Aug 2026).**
Notes from a review of the streaming path against P-SWAMP's real target — grid
data from backend streams to the browser, where **throughput and latency matter**.
These may not survive contact with a real feed.

**The stack itself seems sound:** FastAPI/Starlette on `uvicorn[standard]` (uvloop
+ httptools + `websockets`) is a legitimately fast Python WS stack, React/Vite is
fine as a shell. The risk is in the *patterns* on the streaming path. Roughly
ordered by expected impact. The review predates `pswamp_web/`, so items it raised
that the monitor already solves are dropped here: re-serializing the whole window
per tick (deltas, §4.7), a React render per message (`onMessage` bypass, §4.9),
and the charting-library choice (uPlot, §4.9). What follows is what remains open —
for any new high-rate path, and for the older `pmu_test_streamer` demo where it
still applies.

### Server side

1. **One slow client stalls every client.** `ticker()` awaits each send
   sequentially (`pmu_test_streamer/api.py:141-144`); `await ws.send_json(...)`
   awaits the transport, so a bad link backpressures the **shared** ticker.
   The worst structural issue for low latency. *Fix:* per-client outbound queues
   with an explicit overflow policy — for telemetry, **conflate/drop-latest**, not
   buffer (a stale PMU frame late is worse than one never delivered).
2. **`json.dumps` is the wrong encoder at this rate.** Swap for `orjson`/`msgspec`
   (5–10× encode). For real fan-out, encode **once** and `send_bytes`/`send_text`
   to every client rather than re-encoding per socket.
3. **permessage-deflate is on by default, unexamined.** uvicorn's `websockets`
   negotiates compression by default — CPU for little gain on small
   high-frequency frames, plus latency. Set `ws_per_message_deflate=False`
   deliberately, or leave it on if measurement shows bandwidth-bound. Today it's
   neither decision.
4. **GIL / single process is the real ceiling.** Fine today (I/O-bound, tiny
   payloads, one loop). Once real PMU frames are decoded/transformed in Python
   it's one core. Mitigation order: faster codec → numpy batch ops → move ingest
   off the loop → a different runtime for the hot path. The thin-client /
   one-protocol / no-shared-state architecture makes that last a tractable swap;
   preserve that property.
5. **Two smaller ones.** `states` is never evicted
   (`pmu_test_streamer/api.py:45`) — an acceptable demo leak, unbounded with a live
   feed. `except Exception: pass` (`pmu_test_streamer/api.py:209-210`) hides
   exactly the failures we'll chase under load.

### Client side

6. **`JSON.parse` runs on the main thread** (`useServerSocket.ts:59`), competing
   with rendering. At high rates, move socket + decode into a Web Worker and
   transfer typed arrays.

### Protocol

7. **JSON text frames are the choice to revisit first.** PMU data is fixed-schema
   and numeric — ideal for a binary frame decoded straight into a `Float32Array`
   handed to a canvas with no object allocation. Large constant-factor win both
   ends.

### What to do first

**Nothing in the repo currently measures throughput or latency.** Before
optimizing anything above: add a synthetic load generator (N simulated clients at
realistic rates) and an end-to-end timestamp — server tick to browser paint — so
these become measured, not argued. Expectation: item 1 dominates and the rest is
noise until it's fixed. A hypothesis to test, not a conclusion.
