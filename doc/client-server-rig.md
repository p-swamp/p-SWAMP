# P-SWAMP client-server architecture



Driving goals, constraints and principles:
==

- The goal of the pswamp repo is to make it simple for project members to work with PMU/grid data locally, build UI prototype apps, and run those experiments
against real production data from inside TSO infrastructure.

- Should be simple to spin up and work on locally, with good doc. Should also be possible to test basic kubernetes running locally (via minikube) before deploying to remote cluster.

- Should be easy to iterate quickly on backend + frontend code locally. Hot reload of both layers so that changes are immediate.

- Should be easy to add new pages/"subapplications"/experiments: make it super simple to drop in new web pages and backend modules, with api between them

- Should do what we can to prevent people from tripping over each other and break others code/modules (some guardrails, such as basic syntax error checking before push). Probably also some automated testing
at least for a "reference app" to ensure the basic structure of the repo/project stays intact.

- Should have private github repo for partners to contribute to/pull from, without confidential data.
  With a public mirror that we publish to Linux Foundation Energy regularly.

- Consumed PMU/grid data need to be stubbed out, so that deployments in TSO infra fetches from full dataset, while the public
  repo consumes local non-sensitive test data during local development/testing.

- Apis that return sensitive prod data when deployed in SN infra must filter/shape/transform the data to only show what the UI needs to display/convey,
  not send entire dataset to client (production PMU data is K3 graded eg. should not be directly transmitted to a frontend in its raw form)

- Tech stack is as basic as possible, should be as easy as possible now but also make it easy to promote to prod system later if value is clear.
  Python is the research language used so far in the project. 
- React + Typescript is the lingua franca of web dev in 2026, and also main choice in on of the backing TSOs.

- Start with only basic modularization (clear src folder structure separation between different pages/api endpoints in the repo).
  Defer jumping down rabbithole of microservices, separate packages, multi repo etc to begin with.
  Each such decoupling makes the project harder for partners to iterate in quickly!

# How to onboard when you are new to the project

- Clone this repo
- Make sure you are able to run the two scripts that launches the project locally: 
`scripts/start-local-hotloaded-pswamp-server.sh` and `scripts/start-local-hotloaded-pswamp-web-client.sh`
- Make sure the error check script runs ok for you: `scripts/error_check.sh`
- Make sure the smoke test script runs green: `scripts/e2e-smoke-test.sh`
  
Folder structure for client-server specific bits
==

This project started as a single local python project. These folders are what gets *added* alongside the existing
desktop code:

```text
app/          the two deployables — everything that ends up in the container
  client-web/     React + TypeScript + Vite frontend (shadcn/ui, Tailwind).
                  One folder per page under src/pages/. Built to static assets and
                  baked into the server image; no separate frontend service.
  server-python/  FastAPI state server. src/server.py is the only entrypoint (wiring
                  only); one package per api under src/<app>/.
doc/          markdown notes on how the rig works, plus things to follow up later.
k8s/          Kubernetes manifests
scripts/      the stable developer interface — start the server, start the web
              client, run in minikube, etc. Call these rather than the underlying
              docker/npm/uv commands; they stay the same if the tooling changes.
.github/      CI: workflows/quality-checks.yml (checks + tests on pull requests) and
              workflows/build-and-publish.yml (push the container image to GHCR on main)
.githooks/    pre-push hook running scripts/error_check.sh. Opt in per clone with
              `git config core.hooksPath .githooks`.
```

Loose root files that go with the above: `Dockerfile` and `docker-compose.yml`
(build/run the one container), `.dockerignore`, and `AGENTS.md` / `CLAUDE.md` /
`.github/copilot-instructions.md` (agent guidance — `AGENTS.md` is the real one, the
other two point to it). Keeping the web backend's `pyproject.toml` inside
`app/server-python/` rather than at the root is what stops the two Python projects
colliding.


How to run this locally
==

Fire up `start-local-hotloaded-pswamp-server.sh` and
`start-local-hotloaded-pswamp-web-client.sh` to launch locally. The backend runs in
Docker, the frontend in a Vite process; both hot-reload on save.

You only need **two things installed: Docker and Node.js**. You do *not* strictly
need Python locally — the backend runs inside the container.


Prereqs, what to install
==

**1. Docker** (with the Compose v2 plugin)

The backend script uses `docker compose watch`, which needs Compose **2.22+**. Any
current Docker Desktop or Docker Engine has it.

- Linux (Ubuntu/Debian): https://docs.docker.com/engine/install/ubuntu/ — install
  `docker-ce` plus `docker-compose-plugin`.
- Mac/Windows: Docker Desktop, https://docs.docker.com/desktop/

On Linux, add yourself to the `docker` group to avoid `sudo` — **log out and back in
for it to take effect**:

```
sudo usermod -aG docker $USER
```

**2. Node.js 24 or newer** (npm comes with it)

The container builds the frontend with Node 24, so match that or go higher.

- Any platform: https://nodejs.org/ (LTS), or a version manager (`nvm`, `fnm`, `mise`).
- Ubuntu/Debian: apt's `nodejs` is often too old — prefer nodesource or a version
  manager.

Check:

```
docker compose version      # 2.22+
docker compose watch --help # should print help, not "unknown command"
docker run hello-world      # daemon reachable without sudo
node --version              # v22 or newer
```


Running it locally in dev mode
==

Two terminals, backend first:

```
# terminal 1 — state server on http://127.0.0.1:8000
./scripts/start-local-hotloaded-pswamp-server.sh

# terminal 2 — web client on http://localhost:5173 (opens your browser)
./scripts/start-local-hotloaded-pswamp-web-client.sh
```

Open http://localhost:5173. The page talks to the backend through Vite, which proxies
`/api` to port 8000 — so it behaves like the deployed app.

**The first server start is slow** (a minute or two): Docker builds the image and npm
downloads frontend deps. Later runs start in seconds.

What hot-reloads:

- `.py` under `app/server-python/src/**` → Compose copies it in and the server
  reloads in place.
- `.ts/.tsx` under `app/client-web/**` → Vite patches the running page (HMR).

What does **not**: the generated api contract. Change an endpoint or socket message
and the server reloads, but `doc/api/openapi.json` and the client's generated types
stay put until you run `./scripts/generate-api-contract.sh`. Vite doesn't type-check,
so a mismatch is invisible in the browser — `scripts/error_check.sh` catches it.


Running it as a kubernetes service
==

In real deployments the app is one container on kubernetes, serving both the frontend
and the api on the same port. The frontend is static assets that talk to `/api` on
the same host/port. Test this "prod mode" locally in minikube with
`scripts/start-pswamp-in-local-minikube-cluster.sh`.


Build pipeline (CI)
==

Two workflows under `.github/workflows/`: `quality-checks.yml` gates pull
requests, and `build-and-publish.yml` publishes every change to `main` (and any
`v*` tag) to **GHCR** — `ghcr.io/<owner>/p-swamp`.

```
docker pull ghcr.io/<owner>/p-swamp:latest
```

This is a public container build, that TSO can mirror/pull into their own infra.

Client-server architecture: many pages, one app
==

The project holds several small **pages/"subapplications"** rather than one app: the
web client is a single-page app routed client-side with react-router, and the backend
is one process that routes each api to its own package. One deployable serves it all
from one origin — nothing per-page to deploy or configure.

One real application and two scaffold demos:

| Page URL | Api | What                                              |
|---|---|---------------------------------------------------|
| `/` (grid monitor) | `/api/time-window/ws`, `/api/islanding/ws`, `/api/phasors/ws`, `/api/app-status/ws`, `/api/grid/model` | Dashboard of panels over a recorded Nordic 44 PMU stream replayed through p-SWAMP's monitoring applications |
| `/time-window`, `/phasors`, `/islanding`, `/app-status` | as above | The same panel components, full-size — focused views, not copies |
| `/reference-subapp` | `/api/reference-subapp/ws` | The reference example: a per-client counter, generated by `generate-new-subapp.sh`, and the stack's end-to-end smoke test |
| `/pmu-test-streamer` | `/api/pmu-test-streamer/ws` | Older demo, slated for retirement: streams a canned sample of simulated PMU records line by line |

The Api column lists the *sockets* a page opens (where its state comes from). A page
with controls also POSTs commands to its app's prefix — see "The api between client
and backend".

The grid monitor is the real one; the last two are scaffold demos.
`/reference-subapp` is what `generate-new-subapp.sh` writes and the example every doc
points at — copy it, and click it after a refactor or an upgrade to check the whole
seam works. `/pmu-test-streamer` predates it and is on its way out. A new *p-SWAMP*
view is a panel in the monitor, not a new page — see "Adding a p-SWAMP view" in
`AGENTS.md`.


### Adding a new page/subapp: just run the script

```
./scripts/generate-new-subapp.sh grid-overview "Grid Overview"   # url-name, nav label
```

It does every step in the two sections below and leaves a working subapp: a nav
entry, a page at `/grid-overview`, and a WebSocket to a new backend package holding a
per-client counter you can bump and reset. Replacing that counter with the real thing
is the only work left. The files it writes come from `scripts/templates/`; edit those
to change what a subapp starts life as. Read on to see what it wired up, or to do it
by hand.


### Frontend

Layout under `app/client-web/src/`:

```
pages/            one FOLDER per page — the thing you add
  reference-subapp/
    ReferenceSubappPage.tsx     the page itself
    useReferenceSubappSocket.ts its websocket hook + its commands
  grid-monitor/
    GridMonitorPage.tsx, plus one folder per panel
App.tsx           the route table: which URL renders which page
components/       shared across pages only
  AppLayout.tsx   nav bar + shell every page renders inside
  ui/             shared shadcn/ui building blocks
hooks/
  useServerSocket.ts  the websocket plumbing every page's hook builds on
lib/              servers.ts (each app's ws path + the serving-origin url), utils.ts
```

A page keeps its own parts in its own folder, named after the route. Things move to
`components/` or `hooks/` only once a *second* page needs them.

**To add a page**, three small edits (all done by `generate-new-subapp.sh`):

1. New folder `src/pages/my-thing/` with `MyThingPage.tsx`, plus whatever only that
   page uses (copy `src/pages/reference-subapp/`).
2. In `src/App.tsx`: `<Route path="my-thing" element={<MyThingPage />} />`
3. In `src/components/AppLayout.tsx`, add `{ to: '/my-thing', label: 'My Thing' }` to
   `NAV_ITEMS`.

Vite hot-reloads changes, and deep links (a hard refresh on `/my-thing`) work in dev
and the container because the backend serves the SPA shell for unknown paths.

### Backend

Same idea, one folder per api. Layout under `app/server-python/src/`:

```
server.py         the one entrypoint: which URL prefix goes to which package,
                  plus /healthz and serving the web client. No app logic here.
shared.py         helpers the packages share. Not an api itself.
reference_subapp/ one package per api — the thing you add
  __init__.py     what the package exposes: router (+ lifespan if it needs one)
  api.py          the endpoints: the /ws websocket and the POST commands
  model.py        the app's own domain logic
pmu_test_streamer/  the older demo, on its way out; it also ships a data file
  sample_data.txt  the streamed records — 300 lines of *simulated* PMU data
                   from the Nordic 44 sim, committed as a static test fixture
pswamp_web/       the p-SWAMP web layer: a package of page packages
```

**To add an api**, two small edits (also done by `generate-new-subapp.sh`):

1. New folder `src/my_thing/` (copy `src/reference_subapp/`), whose `__init__.py`
   exposes a `router`, plus `lifespan` if it needs background work.
2. In `src/server.py`, add one `APPS` entry:
   `AppEntry("my-thing", my_thing, "What it is.")`.

Everything the package declares is served under that prefix — the reference subapp's
`"/ws"` becomes `/api/reference-subapp/ws`. Endpoints all live under `/api/`, which
keeps them clear of the page URLs and is what dev forwards to the backend. The folder
is `my_thing` (underscores — Python imports it) while the URL is `my-thing`, matching
the page route.

Data files live inside the package that reads them (like the streamer's
`sample_data.txt`); they ship automatically.


The api between client and backend
==

**Two directions, two transports: commands up over REST, state down over the
WebSocket.** `the-client-server-api.md` is the full account — the contract, both call
paths, the failure semantics. This is the one-screen version.

Each subapp exposes a WebSocket at `/api/<app>/ws`, downstream only: the server pushes
`{type: 'state', ...}` on connect and after every change (including unprompted pushes
from a server-side ticker), and the client renders it. Nothing goes up that socket;
the server's receive loop only notices a disconnect.

Everything a user can trigger is a `POST` under the same `/api/<app>` prefix, one url
per operation:

```
POST /api/reference-subapp/count/bump?client_id=…
POST /api/islanding/alarms/<uuid>/acknowledge?client_id=…
POST /api/time-window/selection?client_id=…        {"channels": [5, 9]}
```

`client_id` is the value the sockets carry — one per browser profile, from
`src/lib/clientId.ts` — which makes a command apply to the pipeline the page is
watching. The reply is a small `CommandAck`, deliberately *not* the new state: state
arrives on the socket, so there is one path for it and nothing to reconcile.

Why it is worth a round trip per click: every operation is a row in the Network tab
and a line in the access log with a status code, and a rejected command says *why*
(422 for a bad sequence name, 404 for an unknown alarm) rather than failing quietly.

**Both halves are described by a generated contract** — `doc/api/openapi.json`,
committed, with the client's TypeScript generated from it and `error_check.sh` failing
on drift. Socket messages are in there too (OpenAPI has no native notion of them);
`the-client-server-api.md` covers how, and how to change the api without breaking
anyone.

Same origin in dev and prod, both transports: the shipped image serves the frontend
itself, and Vite proxies `/api` to the backend in dev.


Authentication
--
For the foreseeable future, pswamp implements no auth of its own in the web→backend
layer, leaving that to the system it is deployed within (for instance, by supporting reverse proxying)

The only client identity we implement is an integer clientId the frontend persists in
browser localStorage.


Performance/profiling
--

TODO: We try not to complicate the architecture until we need it, which means we need
good metrics on how it's behaving. TBD!


Server state
--

**Every connected client gets its own PMU stream** — its own replay of the recording,
its own copies of the monitoring applications, its own alarms and detected islands.
Open the grid monitor and you watch the disturbance from the beginning, whoever else
is on the server and however long it has been up.

This is the opposite of how it started, and the reasoning is worth keeping. The first
version ran one pipeline for the whole process, on the grounds that there is one grid
and two operators seeing different frequencies would be a bug. True of a control room;
false of this, which is a rig for exploring recorded data, where a visitor wants the
event from the start rather than to join someone else's replay half way through. The
useful unit is one timeline per viewer.

### Lifecycle

```
first socket connects  ->  pipeline built, replay starts at 0s
sockets come and go    ->  same pipeline, still replaying
last socket closes     ->  keeps replaying, idle timer starts
reconnect within 5 min ->  rejoins the same stream, mid-flight
5 min with nobody      ->  torn down; next connect starts fresh at 0s
```

- **`?client_id=` identifies the browser, not the tab or the socket.** One random
  integer per browser profile in `localStorage`
  (`app/client-web/src/lib/clientId.ts`), so every socket the page opens carries the
  same value — the grid monitor opens **five** at once and they must all resolve to
  one pipeline. Persisted rather than rolled per mount, so a reload, navigation or
  crashed tab all rejoin the same stream.
- **`HubRegistry` owns the lifecycle** (`app/server-python/src/pswamp_web/hub.py`) —
  the only thing that constructs a pipeline, holding a per-client lock so five
  simultaneous first-connects build one, not five.
- **A pipeline outlives its sockets by design.** Closing the last one starts an idle
  timer instead of tearing down, which makes a reload cheap.
- **A hard cap** (`MAX_PIPELINES`, currently 8). At the cap a new client reclaims the
  least-recently-used pipeline nobody is watching; if every one has a live socket the
  connection is refused with WebSocket close code 1013 and the client shows a banner
  instead of retrying forever.

### What it costs, and why the cap exists

A pipeline is **four OS threads** (three monitoring applications plus the replay
player) and roughly **30 MB** resident, dominated by the 30-second measurement window.

- **Memory is the binding constraint, not CPU.** A pipeline is ~1.4% of a core; eight
  are nothing. But freed memory is not returned to the OS, so **peak RSS follows the
  cap, not the typical load** — which is why both k8s manifests size
  `resources.limits.memory` from `MAX_PIPELINES`.
- **The GIL is the real ceiling.** Every one of those threads runs Python bytecode,
  contending with the event loop that serialises WebSocket messages. That, more than
  any single resource, is why the cap is single-digit.

The recording itself is the one thing still shared: ~10 MB of read-only arrays, loaded
once and handed to every pipeline (`load_recording()` is cached). Safe because
`Recording` is frozen and the decoder copies each row before touching it.

### What this still does not give you

- **One replica only.** Pipelines live in one process's memory, so the manifests are
  `replicas: 1`. A second pod would run its own replays and the Service would scatter
  clients between them — and a client whose sockets landed on different pods would see
  different instants on one screen.
- **Restarts reset everyone.** Nothing is persisted; every client starts over at 0 s.
- **`client_id` is unauthenticated.** Supply someone else's and you share their
  stream. A routing key, not a credential.
- **Clearing site data is a new identity.** The id lives in `localStorage`, so
  clearing it (or a private window) gets a fresh pipeline — also the easy way to force
  a restart from 0 s.

  
Adding a dependency
--

Both sides work the same way: a manifest you edit, and a generated lockfile that pins
exact versions. Commit both; never commit the install directory.

| | Python (`app/server-python/`) | Web client (`app/client-web/`) |
|---|---|---|
| You edit | `pyproject.toml` | `package.json` |
| Generated lock | `uv.lock` | `package-lock.json` |
| Install dir (never committed) | `.venv/` | `node_modules/` |
| Re-resolve after editing | `uv lock` | `npm install` |

```
# Python: add the requirement to [project.dependencies], then
(cd app/server-python && uv lock)
```

The manifest states a compatible *range*; the lockfile pins the one exact version of
every package everyone gets. Re-locking keeps existing versions, so an upgrade is a
deliberate `uv lock --upgrade`, never a side effect. `./scripts/error_check.sh` (and
the Docker build) fail if the two drift.

Updating dependencies
--

Good hygiene to update often, to stay ahead of supply-chain attacks. One script does
the whole repo — both Python projects and the web client, manifests and lockfiles:

```
./scripts/update-dependencies.sh          # TARGET=minor to skip major-version jumps
```

It produces a *candidate diff*: run it on a branch, read the report, run the app and
click through, then open a PR so someone else reads the same diff. The manifests have
a `CODEOWNERS` entry so that lands in front of a reviewer.

Read its **"What actually moved"** report, not the lockfile diff — ~95% of a lockfile
diff is per-wheel sha256 hashes, so one numpy bump rewrites ~40 lines while moving one
version. The report prints the versions, direct deps first and transitive ones as a
count (`VERBOSE=1` lists those too).

One thing to expect: on the npm side the script moves the *ranges* themselves; on the
Python side it can't (`uv lock --upgrade` respects `pyproject.toml`'s bounds, and uv
has no `npm-check-updates`). So a capped dependency needs a hand edit first, and the
script ends by listing which ones are held back and how far they could go. The script
header covers the rest — what it runs, why, and how to recover from a half-finished run.

Optional extras
--

Needed only for the checks and alternative run modes, not the two scripts above:

- **uv** (https://docs.astral.sh/uv/) — runs the backend directly without Docker
  (`cd app/server-python && uv run src/server.py`), manages
  `app/server-python/pyproject.toml` + `uv.lock`, and provides the linter for
  `./scripts/error_check.sh`. Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **minikube + kubectl** — only for
  `./scripts/start-pswamp-in-local-minikube-cluster.sh`, which tests the real image
  on a local cluster. That script also preflights the api contract, so it wants `uv`
  and `npx` too (`NO_CHECK=1` skips both the check and the requirement).


How the project/core team collaborates with the wider open source community
==

_See `how-the-project-interacts-with-open-source-contributors.md`_

