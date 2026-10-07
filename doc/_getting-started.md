# Getting started

p-SWAMP's client-server stack is a Python server that runs analysis modules
over PMU data, and a React web client that shows their results. This page gets
it running on your machine, then points to the doc for what you are here to do.

Everyone starts with the first section. The other four are independent: go to
the one that matches your work.

The original Qt desktop application is not covered here; see the root
[`README.md`](../README.md).

## Starting/testing the project

**Install** Docker (with Compose 2.22 or newer) and Node.js 24 or newer.
"Prereqs, what to install" in [`client-server-rig.md`](client-server-rig.md)
has the install links and a check for each.

**Start it**, in two terminals, the server first:

```
./scripts/start-local-hotloaded-pswamp-server.sh      # the server and its services, in Docker
./scripts/start-local-hotloaded-pswamp-web-client.sh  # the web client, on http://localhost:5173
```

The first start takes a minute or two, while Docker builds the image. After
that a saved `.py` or `.tsx` file reloads on its own.

**Look around** at http://localhost:5173:

Before your first pull request, read
[`how-the-core-contributors-work-together.md`](how-the-core-contributors-work-together.md):
the git workflow, and the sign-off every commit needs.

## How to add analysis modules

*For you if you write the analysis: an algorithm over PMU data.*

A module is one analysis. It reads one kind of message (PMU frames, or another
module's results) and publishes a result. It is one folder holding its code
and its tests, and you can write and test it with no server, message broker or browser
running.

Generate a working one, then replace its placeholder analysis:

```
./scripts/generate-new-module-with-frontend.sh peak-frequency "Peak frequency"
```

That writes the module in `modules/pswamp_modules/peak_frequency/`, its tests,
and a page at `/peak-frequency` showing its latest result. Restart the server
script afterwards.

Read:

- [`module-cookbook.md`](module-cookbook.md): the recipe. Part 1 is the
  module; the later recipes cover commands, chaining one module onto another,
  batch queries, and a process of its own for a heavy module.
- [`modules/README.md`](../modules/README.md): the folder layout, and what a
  module may import.
- `frame_stats/`, `excursion/` and `range_summary/` in
  `modules/pswamp_modules/`: three working modules to read.

## How to add user interfaces

*For you if you build what the user sees.*

The web client is React and TypeScript (Vite, shadcn/ui, Tailwind), with one
folder per page under `app/client-web/src/pages/`. It holds no state: a user
action goes up as a POST, and the page renders what the server pushes down a
WebSocket.

| You want | Start from | Read |
|---|---|---|
| a page showing a module's results | the page the module generator wrote | "Part 2: The frontend" in [`module-cookbook.md`](module-cookbook.md) |
| a page with its own small web API, no module | `./scripts/generate-new-subapp.sh grid-overview "Grid Overview"` | "Adding a new page/subapp" in [`client-server-rig.md`](client-server-rig.md) |
| a new panel in the grid monitor | a copy of `app/client-web/src/pages/grid-monitor/app-status/` | "Adding a p-SWAMP view" in [`AGENTS.md`](../AGENTS.md) |
| a new button or field on an existing page | that page's `api.py` and socket hook | "Common tasks" in [`the-client-server-api.md`](the-client-server-api.md) |

The client's types are generated from the server's code. After changing an
endpoint or a socket message, run `./scripts/generate-api-contract.sh` and
commit what it changes. `error_check.sh` fails until you do.

## Understanding the overall architecture

*For you if you need the whole picture before changing a part.*

Read in this order, stopping when you know enough:

1. [`client-server-rig.md`](client-server-rig.md): the goals and constraints,
   the repo layout, and how pages and web APIs are organised.
2. [`server-data-architecture.md`](server-data-architecture.md): how PMU data
   gets from a source, through modules, to the browser, and how a command gets
   back up. Start with "Vocabulary" and "The picture".
3. [`the-client-server-api.md`](the-client-server-api.md): the seam between
   browser and server, and the generated contract both sides are checked
   against.
4. [`adr/`](adr/): why the larger choices were made.

[`AGENTS.md`](../AGENTS.md) is the detailed reference. It is written for
coding agents, and holds the conventions and the reason behind each.

Where the code is:

| Folder | What it holds                                                                                  |
|---|------------------------------------------------------------------------------------------------|
| `app/client-web/` | The web client.                                                                                |
| `app/server-python/` | The server: one package per web API under `src/`.                                              |
| `core/` | `pswamp_core`: messages, transport, the module contract, data gateway, player, pipelines.      |
| `modules/` | `pswamp_modules`: the analysis modules, the pipelines that combine them, example data sources. |
| `src/pswamp/` | The original desktop package. The grid monitor runs its monitoring applications.               |
| `scripts/` | Every developer command. Call these, not docker, npm or uv directly.                           |
| `Dockerfile`, `docker-compose.yml`, `k8s/` | The container image, and the two local ways to run it.                                         |
| `e2e/` | The Playwright browser tests.                                                                  |

Imports go one way: the server imports the modules and the core, the modules
import the core, the core imports neither.

NOTE: The grid monitor does not run on that module architecture yet. Its analyses
(islanding, line outage) are the desktop package's, run through
`app/server-python/src/pswamp_web/`.
[`WIP-context-port-from-qt-to-web-frontend.md`](WIP-context-port-from-qt-to-web-frontend.md)
covers that port and what remains of it.

## How to deploy/run it

*For you if you run p-SWAMP somewhere other than a laptop, or connect it to
real data.*

p-SWAMP is one Docker image, built from the root `Dockerfile`. As the server
it serves the web client and the API on one port; the same image, started with
another command, is a module worker. Which modules a worker runs, and what
data the server reads, is set by environment variables.

Two ways to run it locally:

| Command | What runs |
|---|---|
| `./scripts/start-local-hotloaded-pswamp-server.sh` | Docker Compose: the server, two module workers, a remote data stub and Kafka, with hot reload. |
| `./scripts/start-pswamp-in-local-minikube-cluster.sh` | The same five on a local Kubernetes cluster, from `k8s/p-swamp-local.yaml`. Needs minikube and kubectl. |

A real deployment:

- **Builds its own image** from the `Dockerfile`, into its own registry.
- **Starts from `k8s/p-swamp-local.yaml`** and changes the image, the ingress,
  the broker and the data sources. "Deployment" in
  [`server-data-architecture.md`](server-data-architecture.md) lists each
  change.
- **Runs a small REST service in front of its PMU store**, which p-SWAMP
  reads history through.
  [`remote-data-integration-contract.md`](remote-data-integration-contract.md)
  specifies it.
- **Adds its own authentication** in front. p-SWAMP has none.

The repo holds no deployment-specific configuration and no secrets. The
manifests in it are local examples.
