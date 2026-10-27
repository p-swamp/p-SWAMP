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

- The public open source repo does not contain any TSO config/details, nor any explicit authentication.
- Any deployments of the repo in the wild must bolt on their own auth, config etc.

- Consumed PMU/grid data need to be stubbed out, so that deployments in TSO infra fetches from full dataset, while the public
  repo consumes local non-sensitive test data during local development/testing.

- Apis that return sensitive prod data when deployed in TSO infra must filter/shape/transform the data to only show what the UI needs to display/convey,
  not send entire dataset to client (production PMU data is K3 graded eg. should not be directly transmitted to a frontend in its raw form)

- Tech stack is as basic as possible, should be as easy as possible now but also make it easy to promote to prod system later if value is clear.
  Python is the research language used so far in the project. Eeact + Typescript is the lingua franca of web dev in 2026, and also main choice inside of the currently backing TSO(s).

- Start with only basic modularization (clear src folder structure separation between different pages/api endpoints in the repo).
  Defer jumping down rabbithole of microservices, separate packages, multi repo etc to begin with.
  Each such decoupling makes the project harder for partners to iterate in quickly!

# How to onboard when you are new to the project

- Clone this repo
- Make sure you are able to run the two commands that launch the project locally:
`uv run pswamp dev server` and `uv run pswamp dev client`
- Make sure the error check runs ok for you: `uv run pswamp check`
- Make sure the smoke test runs green: `uv run pswamp test smoke`

Folder structure for client-server specific bits
==

This project started as a single local python project. The desktop code now lives
in `desktop/`, and these folders are what was *added* alongside it:

```text
app/          the two deployables — everything that ends up in the container
  client-web/     React + TypeScript + Vite frontend (shadcn/ui, Tailwind).
                  One folder per page under src/pages/. Built to static assets and
                  baked into the server image; no separate frontend service.
  server-python/  FastAPI state server. src/server.py is the only entrypoint (wiring
                  only); one package per api under src/<app>/.
models/       pswamp-models: every message of the server data architecture, one
              package per producer (pydantic only).
core/         pswamp-core: transport, the Module and SourceModule contracts, the
              run's router, pipelines.
modules/      one Python project per analysis module or data source
              (modules/<name>/: code, tests, README, examples).
pipelines/    one pipeline file per app (<app>.toml): its modules and sources.
desktop/      the original Python + Qt application, with its own lock.
doc/          markdown notes on how the rig works, plus things to follow up later;
              doc/adr/ holds the architecture decision records.
k8s/          Kubernetes manifests
tools/        the `pswamp` CLI (`uv run pswamp --help`), the stable developer
              interface — start the server, start the web client, run in minikube,
              etc. Call it rather than the underlying docker/npm/uv commands; it
              stays the same if the tooling changes, and runs on Windows too.
e2e/          Playwright browser specs (`uv run pswamp test playwright`)
.github/      CI: workflows/quality-checks.yml (checks + tests on pull requests, on
              Linux and Windows) and workflows/build-container.yml (builds the image
              and pushes it to a private registry package for core contributors)
.githooks/    pre-push hook: checks every pushed commit is signed off (DCO), then
              runs uv run pswamp check. Opt in per clone with
              `git config core.hooksPath .githooks`.
```

Loose root files that go with the above: `Dockerfile` and `docker-compose.yml`
(build/run the one container), `.dockerignore`, `pyproject.toml` + `uv.lock` (the uv
workspace that ties `models/`, `core/`, `modules/*`, `tools/` and
`app/server-python/` under one lockfile), and `AGENTS.md` / `CLAUDE.md` /
`.github/copilot-instructions.md` (agent guidance — `AGENTS.md` is the real one, the
other two point to it). The desktop package keeps its own `pyproject.toml` and lock in
`desktop/` rather than joining the workspace, which is what stops Qt and the web
backend colliding in one dependency resolution.


How to run this locally
==

Fire up `pswamp dev server` and
`pswamp dev client` to launch locally. The backend runs in
Docker, the frontend in a Vite process; both hot-reload on save.

You only need **two things installed: Docker and Node.js**. You do *not* strictly
need Python locally — the backend runs inside the container.


Prereqs, what to install
==

**1. Docker** (with the Compose v2 plugin)

`pswamp dev server` uses `docker compose watch`, which needs Compose **2.22+**. Any
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
uv run pswamp dev server

# terminal 2 — web client on http://localhost:5173 (opens your browser)
uv run pswamp dev client
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
stay put until you run `uv run pswamp api generate`. Vite doesn't type-check,
so a mismatch is invisible in the browser — `uv run pswamp check` catches it.


Running it as a kubernetes service
==

In real deployments the app is one container on kubernetes, serving both the frontend
and the api on the same port. The frontend is static assets that talk to `/api` on
the same host/port. Test this "prod mode" locally in minikube with
`uv run pswamp deploy minikube`.


Build pipeline (CI)
==

Two workflows under `.github/workflows/`: `quality-checks.yml` gates pull
requests, and `build-container.yml` builds the container image, checks it
starts, and pushes it to a **private** GitHub Container Registry package.

**That image is for core contributors only.** This repo must not be a public
source of binaries, so the package is private, and it cannot be made public for
this repo.

- **`main`:** built automatically on every change.
- **Any other branch:** built only by hand. On github.com: Actions →
  build-container → "Run workflow" → pick the branch. Needs write access.
- **Name:** `ghcr.io/<owner>/p-swamp:<branch>-<full commit sha>`. There is no
  `latest`; a tag never moves.
- **Pulling:** needs access to the package and a personal access token (classic)
  with `read:packages`.

```
echo $TOKEN | docker login ghcr.io -u <github user> --password-stdin
docker pull ghcr.io/<owner>/p-swamp:<branch>-<full commit sha>
```

The build context is the repo root (the image holds both the web client and the
desktop package's `src/`), and `GIT_SHA` is what the client footer shows on a
deployed origin. Tag the image with the commit it was built from rather than a
moving tag, so a deployment can be pinned and a rollout is triggered by a change
of image. `uv run pswamp deploy minikube` is the local
rehearsal of that path: it builds the same Dockerfile into minikube and applies
`k8s/overlays/minikube` (`k8s/README.md`).

Client-server architecture: many pages, one app
==

The project holds several small **pages/"subapplications"** rather than one app: the
web client is a single-page app routed client-side with react-router, and the backend
is one process that routes each api to its own package. One deployable serves it all
from one origin — nothing per-page to deploy or configure.

One real application and two scaffold demos:

| Page URL | Api | What                                              |
|---|---|---------------------------------------------------|
| `/` (grid monitor) | `/api/time-window/ws`, `/api/islanding/ws`, `/api/phasors/ws`, `/api/line-outage/ws`, `/api/app-status/ws`, `/api/grid/model` | Dashboard of panels over one live simulation of the grid in the CIM graph, analysed by the `islanding-detection` and `line-outage` modules, shared by every client |
| `/time-window`, `/phasors`, `/islanding`, `/line-outage`, `/app-status` | as above | The same panel components, full-size — focused views, not copies |
| `/reference-subapp` | `/api/reference-subapp/ws` | The reference example: a per-client counter, generated by `pswamp new subapp`, and the stack's end-to-end smoke test |
| `/pmu-test-streamer` | `/api/pmu-test-streamer/ws`, `/api/errors/ws` | The server data architecture's worked example: a recorded, a live and a remote PMU source through a core pipeline, with player controls and three modules |

The Api column lists the *sockets* a page opens (where its state comes from). A page
with controls also POSTs commands to its app's prefix — see "The api between client
and backend".

The grid monitor is the real one. `/reference-subapp` is what
`pswamp new subapp` writes and the example every doc points at — copy it, and
click it after a refactor or an upgrade to check the whole seam works.
`/pmu-test-streamer` is the worked example of the server data architecture
(`doc/server-data-architecture.md`); a new module and its page start from
`pswamp new module` (`doc/module-cookbook.md`). A new
*p-SWAMP* view over the monitor's data is a panel in the monitor, not a new page —
see "Adding a p-SWAMP view" in `AGENTS.md`.


### Adding a new page/subapp: just run the generator

```
uv run pswamp new subapp grid-overview "Grid Overview"   # url-name, nav label
```

It does every step in the two sections below and leaves a working subapp: a nav
entry, a page at `/grid-overview`, and a WebSocket to a new backend package holding a
per-client counter you can bump and reset. Replacing that counter with the real thing
is the only work left. The files it writes come from `tools/src/pswamp_tools/templates/`; edit those
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

**To add a page**, three small edits (all done by `pswamp new subapp`):

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
pmu_test_streamer/  the web API (api.py) of the server data architecture's
                    worked example. Its modules are projects in modules/<name>/;
                    its pipeline is pipelines/pmu-test-streamer.toml and its
                    sources are projects in modules/ (sample-replay, with the
                    recording (sample_data.txt: 300 lines of *simulated* PMU data
                    from the Nordic 44 sim, committed as a static test fixture))
errors/           the error tray's backend
grid_monitor/     the grid monitor's backend: live.py (LIVE, the shared live run
                  every panel reads) and one page package per panel (app_status,
                  grid, time_window, phasors, islanding, line_outage)
pswamp_web/       the grid monitor's wire layer: message models and send_state,
                  the socket pumps, SessionRegistry, the alarm store
```

**To add an api**, two small edits (also done by `pswamp new subapp`):

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
`src/lib/clientId.ts` — which makes a command apply to the state the page is
watching: that client's own (the streamer's run, a view's channel selection), or, on
the grid monitor, the state every client shares, with the id saying whose browser the
command came from. The reply is a small `CommandAck`, deliberately *not* the new state: state
arrives on the socket, so there is one path for it and nothing to reconcile.

Why it is worth a round trip per click: every operation is a row in the Network tab
and a line in the access log with a status code, and a rejected command says *why*
(422 for a bad sequence name, 404 for an unknown alarm) rather than failing quietly.

**Both halves are described by a generated contract** — `doc/api/openapi.json`,
committed, with the client's TypeScript generated from it and `pswamp check` failing
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

**The grid monitor shows one live grid, shared by every client.** One real-time
simulation of the grid in the CIM graph (the `rtsim-from-cim` source), one 30-second
measurement window, one islanding assessment, one alarm list, one line-outage log.
Whoever opens the page, and whenever, sees the same instant.

It is the shared live run of the `grid-monitor` pipeline
(`pipelines/grid-monitor.toml`: that source and the `islanding-detection` and
`line-outage` modules), which `LIVE` (`app/server-python/src/grid_monitor/live.py`)
follows off the transport for the whole process — entered as a service in
`server.py`, before any app. Every panel reads `LIVE` on the event loop; there are no
threads in the web layer.

This is the opposite of how it was, and the reasoning then is worth keeping. An
earlier version gave every connected client its own replay of a recorded Nordic 44
stream, through its own copies of the desktop package's monitoring applications, on
the grounds that a rig for exploring recorded data wants each visitor to see the event
from the start. A live grid has no start: there is one grid, and two operators seeing
different frequencies would be a bug. Its per-client pipelines, their cap and their
idle eviction went with the recording.

- **An alarm is everyone's.** Acknowledging, silencing or annotating one
  (`POST /api/islanding/alarms/<uuid>/…`) applies for every viewer, and every open
  view is sent the change at once (`LIVE.nudge()`).
- **A view's channel selection is still its own.** The time window keeps what each
  open view plots per connection (`SessionRegistry` in
  `grid_monitor/time_window/api.py`); a selection command from a browser with no open
  view is a 404.
- **`?client_id=` identifies the browser, not the tab or the socket.** One random
  integer per browser profile in `localStorage`
  (`app/client-web/src/lib/clientId.ts`), so every socket the page opens carries the
  same value. On the grid monitor it no longer chooses the data, but every socket and
  command still carries it, and a socket without a usable one is refused (1008).

The PMU test streamer is the other way round: each client gets its own run over a
recording, starting at 0 s, while a live source is one shared run that client runs
follow (`doc/server-data-architecture.md`).

### What this still does not give you

- **One replica only.** State lives in one process's memory, so the manifests are
  `replicas: 1`. A second pod would run its own simulation and its own runs, and the
  Service would scatter clients between them — and a client whose sockets landed on
  different pods would see different instants on one screen.
- **Restarts reset everyone.** Nothing is persisted: the alarm list, the window and
  every streamer run start over.
- **`client_id` is unauthenticated.** Supply someone else's and you drive their
  streamer run, or change their channel selection; anyone can acknowledge the shared
  alarms. A routing key, not a credential.
- **Clearing site data is a new identity.** The id lives in `localStorage`, so
  clearing it (or a private window) gets a fresh one — and, on the streamer, a fresh
  run from 0 s.


Adding a dependency
--

Both sides work the same way: a manifest you edit, and a generated lockfile that pins
exact versions. Commit both; never commit the install directory.

| | Python (`app/server-python/`) | Web client (`app/client-web/`) |
|---|---|---|
| You edit | `pyproject.toml` | `package.json` |
| Generated lock | `uv.lock` (at the repo root, the workspace's) | `package-lock.json` |
| Install dir (never committed) | `.venv/` (at the repo root) | `node_modules/` |
| Re-resolve after editing | `uv lock` | `npm install` |

```
# Python: add the requirement to [project.dependencies], then
uv lock    # at the repo root: one lock for the whole uv workspace
```

The manifest states a compatible *range*; the lockfile pins the one exact version of
every package everyone gets. Re-locking keeps existing versions, so an upgrade is a
deliberate `uv lock --upgrade`, never a side effect. `uv run pswamp check` (and
the Docker build) fail if the two drift.

Updating dependencies
--

Good hygiene to update often, to stay ahead of supply-chain attacks. One command does
the whole repo — both Python projects and the web client, manifests and lockfiles:

```
uv run pswamp deps update          # TARGET=minor to skip major-version jumps
```

It produces a *candidate diff*: run it on a branch, read the report, run the app and
click through, then open a PR so someone else reads the same diff. The manifests have
a `CODEOWNERS` entry so that lands in front of a reviewer.

Read its **"What actually moved"** report, not the lockfile diff — ~95% of a lockfile
diff is per-wheel sha256 hashes, so one numpy bump rewrites ~40 lines while moving one
version. The report prints the versions, direct deps first and transitive ones as a
count (`VERBOSE=1` lists those too).

One thing to expect: on the npm side the command moves the *ranges* themselves; on the
Python side it can't (`uv lock --upgrade` respects `pyproject.toml`'s bounds, and uv
has no `npm-check-updates`). So a capped dependency needs a hand edit first, and the
command ends by listing which ones are held back and how far they could go. Its `--help`
covers the rest — what it runs, why, and how to recover from a half-finished run.

Optional extras
--

Needed only for the checks and alternative run modes, not the two dev commands above
(those need only uv, Docker or Podman, and Node.js):

- **uv** (https://docs.astral.sh/uv/) — runs the backend directly without Docker
  (`cd app/server-python && uv run src/server.py`), manages
  `app/server-python/pyproject.toml` + `uv.lock`, and provides the linter for
  `uv run pswamp check`. Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **minikube + kubectl** — only for
  `uv run pswamp deploy minikube`, which tests the real image
  on a local cluster. That command also preflights the api contract, so it wants `uv`
  and `npx` too (`--no-check` skips both the check and the requirement).


How the project/core team collaborates with the wider open source community
==

_See `how-the-project-interacts-with-open-source-contributors.md`_
