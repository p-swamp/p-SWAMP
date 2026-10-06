# The client/server api

The seam between the web client and the state server: its rules, the contract
that describes it, and the machinery underneath. Read as much as you need:

| If you want to… | Read |
|---|---|
| add an endpoint, a field, or a page | [Common tasks](#common-tasks) |
| know which files are generated and which to edit | [Where the contract comes from](#where-the-contract-comes-from) |
| know what the contract covers | [What the contract is](#what-the-contract-is) |
| understand how a click becomes a change | [Upstream](#upstream-how-a-command-reaches-the-server) |
| understand how state reaches the screen | [Downstream](#downstream-how-state-reaches-the-screen) |
| know what a failure looks like | [Error and refusal semantics](#error-and-refusal-semantics) |

For the shorter tour of the whole rig, read `client-server-rig.md`.

The shape of the api
==

**Two directions, two transports.** A user action goes up as an HTTP `POST` under
`/api/<app>/`. The server pushes everything back down a WebSocket at
`/api/<app>/ws` (never anything upstream). A command answers with a small
acknowledgement, never with state — so state travels exactly one path and a client
never has to reconcile the order of two.

```
   BROWSER                                   SERVER (one process, one event loop)

   page component                            FastAPI app  (src/server.py)
        │  onClick                                │
        ▼                                         │  routers mounted per app
   page hook  (useReferenceSubappSocket)          │  under /api/<app>
        │                                         │
        ├──► postCommand() ──── POST ─────────────┼──► command endpoint
        │    lib/commands.ts   ?client_id=…       │      mutates that client's state
        │                      ◄── CommandAck ────┤      then pushes ↓
        │                                         │
        └──► useServerSocket() ◄══ WS frames ═════┴──◄ push task / SocketRegistry
             hooks/useServerSocket.ts   {type:"state",…}
```

Both resolve against **the origin that served the page**. There is no backend
picker; dev imitates production rather than taking a special path.


Where the contract comes from
==

**The Python is the source; everything else is generated.** Ordinary server code
defines the api — each app package's `router` (paths, `operation_id`s, body models,
`CommandAck` replies) and the `WS_MESSAGE` model it pushes. `api_contract.py`
defines nothing: it assembles the document and adds the socket half OpenAPI has no
notion of.

```
   src/<app>/  and  src/pswamp_web/<app>/        ← THE DEFINITION. Edit here.
     router       POST paths, operation_id, body models, CommandAck
     WS_MESSAGE   the pydantic model this package pushes
        │
        ▼
   src/api_contract.py                            ← metadata + the socket half
     title, API_VERSION, description, tag text
     walks APPS for WS_MESSAGE → components.schemas + x-websocket-channels
     install() overrides app.openapi()
        │
        ▼
   tools/dump_openapi.py       imports `server`, asks it for its own document
        │
        ▼
   doc/api/openapi.json        generated, committed — and served live at
        │                      /openapi.json, /docs, /redoc
        │  openapi-typescript
        ▼
   app/client-web/src/api/schema.ts               generated, committed
        │
        ├──► src/api/wire.ts      →  Wire['ReferenceSubappState'] in each hook
        └──► src/lib/commands.ts  →  postCommand, typed against the paths
```

Two consequences, and they are the whole point:

- **Never edit the two generated files.** Change the Python — a route, a model, or
  the metadata in `api_contract.py` — then run
  `uv run pswamp api generate` and commit everything together. A hand-edit
  to `openapi.json` or `schema.ts` is discarded on the next regeneration. See
  [Changing the api](#changing-the-api).
- **The committed contract cannot disagree with the running server**, because
  `dump_openapi.py` asks the app for its own document instead of describing the api
  twice. `pswamp api generate --check` regenerates into a temp dir and diffs;
  `pswamp check` runs that on every push.

For the file-by-file table, see [Where the pieces live](#where-the-pieces-live).


Common tasks
==

### I want to add a command (a new POST) to an existing app

Write it in that app's `api.py`. Give every operation its own url; never build one
endpoint that takes an action name:

```python
@router.post("/count/step", operation_id="reference_subapp_step")
async def step(client_id: ClientId) -> CommandAck:
    """One line saying what it does — this becomes the description in /docs."""
    ...
```

- **Always set `operation_id`, as `<app>_<verb>`** in snake_case
  (`time_window_resync`, `reference_subapp_bump`). A generated client calls that
  name, so choose it deliberately — renaming the handler must never rename
  someone's generated method.
- **Import `ClientId` and `CommandAck`** from `shared` in a standalone app, or from
  `..wire` inside `pswamp_web/` (which may not import the rest of the backend).
- **Taking a body?** Declare a pydantic model in the same file and take it as a
  parameter (`body: ChannelSelection`); FastAPI then rejects a malformed command
  with a 422 before your handler runs.
- **Never return the new state.** `CommandAck` only; state goes down the socket.

Client side, one call. `tsc` checks the path against the contract, so a typo fails
the build:

```ts
const step = useCallback(
  () => fire(postCommand(`${REFERENCE_SUBAPP_API_PATH}/count/step`)),
  [],
)
```

Then run `uv run pswamp api generate` and commit `doc/api/openapi.json`
and `app/client-web/src/api/schema.ts` with the code.

### I want to add a field to a socket message

Add it to the message model — `pswamp_web/wire.py` for the p-SWAMP apps, the app's
own `api.py` for a standalone one — and fill it in wherever `state_message()` (or
the page's push task) builds it.

Run `uv run pswamp api generate` and `Wire['<Model>']` carries the field,
as does the page, which reads the message as the contract types it. There is no
mapping layer to extend: hooks used to rename every field into a camelCase mirror,
so a new field reached the page only if someone remembered to add it there too (and
a `useMemo` that forgot one type-checks fine). Render it and you are done.

Commit both generated artifacts with the model change.

### I want to add a whole new page and its api

```
uv run pswamp new subapp flow-map "Flow Map"
```

The generator writes both halves, patches the four registries, regenerates the
contract and runs the checks — the new app joins the contract with **no registry
entry to add** (see "How a package joins the contract"). Commit both generated
artifacts with the new folders.

> **To see every moving part a subapp needs, run that generator and read the diff.**
> It writes a page folder under `app/client-web/src/pages/<slug>/` and a backend
> package under `app/server-python/src/<pkg>/` — socket endpoint, pydantic models,
> two POST commands over a per-client counter, the hook and the view — patches the
> four registries (`server.py`, `lib/servers.ts`, `App.tsx`, `AppLayout.tsx`), and
> regenerates the contract. Run it on a throwaway name to look; `git status` shows
> what it touched, and deleting the two new folders plus reverting the four patched
> files undoes it.

### I want to add a plain GET (something static, not pushed)

Same as a command, but **declare a response model** — a bare `-> dict` publishes as
an untyped `object`, leaving the client casting an implicitly-`any` body:

```python
@router.get("/channels", operation_id="time_window_channels")
async def list_channels() -> ChannelCatalogue:
    return ChannelCatalogue(channels=_channels())
```

Use a GET only for what never changes (grid topology, channel catalogue); put
anything that changes on the socket. Then regenerate and commit.

### `pswamp check` is failing on "api contract (spec matches code)"

You changed the api and left the committed contract behind. The check prints the
diff:

```
uv run pswamp api generate      # regenerate both artifacts
```

then commit both. Hand-edit nothing — that is the whole fix.

### How do I see what the api looks like right now?

Run a server and open `/docs` (Swagger UI, grouped by app) or `/redoc`. Without
one, query the committed file:

```
jq '.paths | keys' doc/api/openapi.json                  # every HTTP operation
jq '.["x-websocket-channels"]' doc/api/openapi.json      # every socket channel
jq '.components.schemas | keys' doc/api/openapi.json     # every model
```

### I renamed a field. Is that a breaking change?

Yes — anyone generating against the contract sees a rename as a removal plus an
addition. Bump `API_VERSION`, regenerate, commit both artifacts, and say so in the
PR. An added optional field breaks nothing and needs no bump. See "Versioning".

### Do I need to regenerate after changing only a docstring?

Yes. Docstrings become operation descriptions, so they land in the generated
artifacts and the check catches them. Regenerate and commit, as for any api change.

------------------------------------------------------------------------------

*The rest is reference: what the contract guarantees, then how the two transports
work underneath it.*


What the contract is
==

**`doc/api/openapi.json`** — an OpenAPI 3.1 document, generated from the server and
committed. It describes:

- **every command**, as an HTTP `POST` with a stable `operationId`, its path and
  query parameters, its request body and its `CommandAck` reply;
- **the two plain GETs** — grid topology and channel catalogue;
- **`GET /healthz`**;
- **every WebSocket message**, as a schema under `components.schemas`, with the
  channels listed under the `x-websocket-channels` extension.

**`app/client-web/src/api/schema.ts`** — TypeScript generated from that document by
`openapi-typescript`, also committed. The client reads it through `src/api/wire.ts`,
the small hand-written layer over it.

The running server serves the identical document at **`/openapi.json`**, rendered
by **`/docs`** (Swagger UI) and **`/redoc`**. One function produces both the served
and committed copy, and `pswamp check` proves it on every push.

> Swagger UI at `/docs` fetches its assets from a CDN, so it needs internet.
> `/openapi.json` and `/redoc` do not.


Which subapp a request belongs to
==

The contract follows the code's organisation. Every operation carries its app's url
name as a tag — `reference-subapp`, `time-window`, `islanding` — and that name is
the `/api/<app>` segment, the server package name with underscores, and the client's
page folder. So `/api/time-window/selection` lives in `time_window/` on the server
and `pages/grid-monitor/time-window/` in the client, and Swagger UI groups it under
`time-window`. Grid-monitor views nest under `pages/grid-monitor/`; standalone pages
like `reference-subapp` live directly under `pages/`. One name, four places, no
lookup table.

`operationId` follows the same rule, `<app>_<verb>` (`time_window_resync`,
`islanding_acknowledge`) — chosen deliberately, since a generated client calls those
names and renaming a handler must not rename someone's generated method.


How a package joins the contract
==

**A package joins by exporting a name.** No registry to add an entry to.

`server.py` already discovers optional features with
`getattr(module, "lifespan", None)`. Socket messages work the same way — a package
exports the model it pushes:

```python
# app/server-python/src/reference_subapp/__init__.py
from .api import ReferenceSubappState, router

WS_MESSAGE = ReferenceSubappState

__all__ = ["WS_MESSAGE", "ReferenceSubappState", "router"]
```

An app that also needs startup/shutdown work exports a `lifespan` beside those —
`pmu_test_streamer` (its pipeline runs and modules) and `pswamp_web` (the pipeline
registry) do.

`api_contract.py` walks the same `APPS` list `server.py` mounts and collects
whatever each package exports under that name. An app with no socket
(`pswamp_web/grid/`, HTTP only) simply omits it.

Discovery does not make omissions silent: `check_apps()` runs when `server.py`
installs the contract and refuses to start if an app serves a WebSocket without
exporting `WS_MESSAGE`. When socket models merge into the HTTP schemas,
`_merge_schemas()` likewise refuses two different shapes with the same model name —
rename one or give it an explicit pydantic title rather than let the document
disagree with itself.

This is why `pswamp new subapp` needs no new anchor to patch: its template
exports `WS_MESSAGE`, so a scaffolded subapp joins the contract the moment it is
written. The generator regenerates both artifacts before it checks — commit them with
the rest.

One rule keeps this working: **push a pydantic model, never a bare dict.** Every
push goes through `wire.send_state`, which takes a `BaseModel` — the model is the
published shape, and the one serialiser is also why a bare `NaN` (which
`JSON.parse` rejects) can never reach the wire. `SocketRegistry.send_to_client` is
that same call, fanned out to whatever sockets one client has open.


Changing the api
==

1. Change the Python — an endpoint, a body model, or a message model.
2. Run `uv run pswamp api generate`.
3. Commit `doc/api/openapi.json` and `app/client-web/src/api/schema.ts` with the
   change.

Skip step 2 and `uv run pswamp check` fails — in the pre-push hook, then again
in CI — printing a diff of what moved. That is deliberate: committing the contract
only buys a **reviewable** change if it rides in the same PR as the code that caused
it. Never hand-edit either generated file (`schema.ts` says so at the top).

### Versioning

Bump `API_VERSION` in `app/server-python/src/api_contract.py` **by hand, on a
breaking change** — a removed or renamed field, a removed operation, a narrowed
type. Additive changes need nothing.

It is manual on purpose: a version that moves on every commit tells a reader
nothing; one that moves only when compatibility breaks becomes the single diff line
that says "coordinate this one". If you bump it, say so in the PR — see "The api
contract" in `how-we-work-together.md`.


Addressing: origin, prefix, client id
==

Three things decide where a request goes and whose state it touches, all settled by
`app/client-web/src/lib/`.

**Origin** — `servers.ts` builds every url from `window.location`:

| helper | produces | used by |
|---|---|---|
| `resolveServerUrl(wsPath)` | `ws(s)://<host><BASE_PATH><path>` | the one WebSocket, in `useServerSocket` |
| `resolveApiUrl(path)` | `http(s)://<host><BASE_PATH><path>` | `postCommand`, and the two plain GETs |

The protocol follows the page's (`https:` → `wss:`), so no code has to know whether
it runs behind TLS.

**Prefix** — `basePath.ts` discovers the mount prefix at runtime, reading its own
`import.meta.url` and cutting at `/assets/`. Remotely the app sits under `/p-swamp/`
behind a reverse proxy that strips the prefix before forwarding, so the *server*
sees plain `/api/...` and the *browser* has to put it back. That is how one image
runs both at a root and under a prefix. It depends on routes staying one segment
deep — that file explains why.

**Client id** — `clientId.ts` resolves one random integer per browser profile,
persists it in `localStorage`, and every socket and command sends it as
`?client_id=` (sockets on the WebSocket url, commands via `postCommand`, so no
caller passes it). That id shards all server state: one id per browser is what makes
the grid monitor's five sockets show **one** server-side pipeline rather than five.
It authenticates **nothing** — send someone else's id and you drive their replay.

The same urls work in dev because Vite proxies the whole `/api` prefix — WebSocket
upgrades included — to the backend on `:8000` (`server.proxy` in `vite.config.ts`).
In the shipped image the server serves the client itself, so every request is
same-origin.


Downstream: how state reaches the screen
==

Client side
--

`useServerSocket(wsPath, options)` (`src/hooks/useServerSocket.ts`) handles the
connection half for every app. It:

1. opens one WebSocket to `resolveServerUrl(wsPath) + '?client_id=' + CLIENT_ID`;
2. reconnects every 2 s while down — **except** after close codes `1008` (id
   rejected) and `1013` (server at pipeline capacity). The server meant those, and
   retrying only makes it worse;
3. runs each frame through `JSON.parse`, drops anything whose `type` is not
   `"state"`, then stores it (`message`) or hands it to `options.onMessage`;
4. tracks a `status` — `connecting` / `online` / `offline` — separating "never
   reached the server" from "an established connection dropped".

It knows nothing about message *shape*. Each page's hook types the payload with the
generated `Wire['<Model>']` and hands it on as-is — snake_case field names included,
because those come from the contract and are checked against it. A hook may still
*derive* (`useLineOutageSocket` parses branch names from channel labels,
`useTimeWindowSocket` accumulates a ring buffer); what it no longer does is rename.

**Reach for the `onMessage` escape hatch when the stream is fast.** Storing a
message in React state costs a render pass — right for a small SVG payload (phasors,
islanding), wrong for a 50 Hz sample stream. `useTimeWindowSocket` therefore keeps
its samples in a `useRef` and notifies the chart through its own `subscribe`, so ten
messages a second trigger zero renders. React re-renders only when something it owns
changes: the channel list, or the connection status.

Server side
--

`src/server.py` does wiring and nothing else. It mounts each app package's `router`
under its prefix from `APPS`, tags it with the app's url slug, composes every
package's `lifespan` into one, serves `/healthz`, and mounts the built client at `/`
last (a `/` mount is greedy and swallows anything registered after it).

From there the two families of app part ways.

**The scaffold demos** keep it minimal. `reference_subapp/` is the whole of it:

- `states: dict[str, ReferenceSubappModel]` — the entire store, keyed by client id;
- `SocketRegistry` (`src/shared.py`) — client id → this client's live sockets, pure
  transport, one instance per app. It is `SessionRegistry` (`pswamp_web/sessions.py`)
  with the socket itself as the session — the same structure the page packages
  register view state in;
- a command handler that mutates one client's state and pushes it, and a socket
  handler that pushes on connect and then only waits.

`pmu_test_streamer/` is the same seam over the server data architecture
(`doc/server-data-architecture.md`): its state is a pipeline run per client, its
commands go to that run's player or modules through `shared.dispatch_command`, and
`shared.push_changes` sends a state message after every change in the run. Copy it
(or run `pswamp new module`) when an app's data comes from PMU
sources and modules.

A client id may briefly hold several sockets — a reconnect overlapping the dying one
— which is why it is a set. `send_to_client` iterates a snapshot and drops any socket
that fails mid-send, so one dead connection cannot break delivery to the rest.

**The p-SWAMP layer** (`src/pswamp_web/`) is the real one, with a pipeline behind
it. Every endpoint opens the same way:

```python
async with connected_hub(ws) as hub:
    if hub is None:
        return
```

`connected_hub` (`pswamp_web/hub.py`) parses `?client_id=`, accepts the socket, and
holds that client's `Hub` for the life of the connection. It refuses in two orders,
deliberately: given **no usable id** it closes *before* accepting, rejecting the
handshake; **at capacity** it accepts *first* and then closes with `1013`, because a
close code only reaches the browser over an established connection — and the client
treats `1013` as terminal.

A `Hub` holds one client's pipeline: a `RecordingPlayer` over the committed Nordic 44
recording, three p-SWAMP monitoring applications each with their own reader, and the
alarm/status/island stores. Only `HubRegistry` constructs one, enforcing three rules:
one pipeline per client however many sockets (a per-client lock, so the monitor's
five simultaneous first-connects build one rather than racing to build five); a
pipeline outlives its sockets by `IDLE_EVICT_SECONDS`, so a reload rejoins the same
stream; and never more than `MAX_PIPELINES`.

Then each page picks one of **two delivery patterns**:

| pattern | apps | how it works |
|---|---|---|
| **Poll the window** | `time_window` (10 Hz), `phasors` (5 Hz), `app_status` (2 Hz) | an `asyncio` task reads the client's window or stores on its own timer and sends |
| **Subscribe to the bus** | `islanding`, `line_outage` | a listener on `hub.bus` offers into an `asyncio.Queue`; the push task blocks on it |

Polling translates directly from what the Qt widgets do, and it keeps a 50 Hz sample
stream from becoming 50 event-loop callbacks a second. Subscribing suits results and
events, which arrive about once a second. Both bus-driven pages re-read the payload
from the hub rather than carrying it on the queue, so a dropped notification costs
latency and never content.

Every page sends through **`send_state()`** (`pswamp_web/wire.py`), never
`ws.send_json`:

```python
await ws.send_text(message.model_dump_json())
```

`json.dumps` emits bare `NaN`/`Infinity` tokens that `JSON.parse` rejects — and NaN
is the *normal* case here, since a `TimeWindow` holds nothing else until it fills.
Routing every page through one function stops a new message type from quietly
reintroducing it. A missing measurement reaches the client as `null`, never `NaN`
(the models declare `float | None` and the server substitutes), and a `TimeWindow`
arrives all-`null` until it fills — normal, not an error. The `wire.py` models are
the schema the Qt front end never needed: its widgets read the very `TimeWindow`
object the application thread writes into.

The thread seam
--

p-SWAMP's monitoring applications are upstream code, running as daemon threads
looping on a blocking read. We leave that as it is. They cross into the event loop at
**exactly two places**:

1. **`Bus.publish_threadsafe()`** (`pswamp_web/bus.py`) → `loop.call_soon_threadsafe`
   → `_deliver` on the loop → synchronous listeners (the stores) and queued
   subscriptions (the pages). The bus is **per pipeline**, so a listener only hears
   its own client's results.
2. **`CountingTimeWindowLabeled.snapshot()`** (`pswamp_web/replay.py`) — reads the
   append counter *and* the data under the window's own lock, so the two describe the
   same instant.

Everything else — WS handlers, push tasks, request handlers — runs cooperatively
scheduled on the one loop and never truly parallel, so none of it needs a lock. Add
a third seam and that stops being reviewable.

The delta protocol
--

`time_window` is the one page where the naive approach fails. A 30 s window of 8
channels at 50 Hz holds 12,000 numbers, and re-sending it 10×/s costs roughly
1.4 MB/s per client. So it sends the window once (`mode: "full"`) and afterwards only
the rows that are new (`mode: "append"`) — measured at ~5.9 KB/s.

The window's append counter makes that possible: `new_rows = appended -
state.last_appended`. Two cases force a full message instead: a fresh selection,
where the client's traces belong to different channels; and a client that has fallen
behind by more than the window, where an append would splice unrelated data onto what
it holds.


Upstream: how a command reaches the server
==

Client side
--

A page hook exposes one named function per operation, each wrapping `postCommand`
from `src/lib/commands.ts`:

```ts
const bump = useCallback(
  () => fire(postCommand(`${REFERENCE_SUBAPP_API_PATH}/count/bump`)),
  [],
)
```

`postCommand(path, options?)` is the only code that sends anything upstream. It fills
in any `{placeholder}` from `options.path` (url-encoding each value), resolves the
url, appends `?client_id=`, sets `Content-Type` only when it carries a body, and
throws a `CommandError` with the status and FastAPI's `detail` on any non-2xx. The
contract types both path and body, so a typo fails `tsc` instead of returning a 404.

Callers log and carry on (`fire` in each hook). The UI treats a command as
fire-and-forget: the resulting state arrives on the socket or not at all, so a failed
command changes nothing — which is what the user already sees. Keep controls
`disabled={!connected}` for the same reason: without a socket the POST still reaches
the server, but its result has nowhere to land.

Server side
--

Every command endpoint declares its caller and its reply the same way:

```python
@router.post("/count/bump", operation_id="reference_subapp_bump")
async def bump(client_id: ClientId) -> CommandAck:
    ...
```

- **`ClientId`** — an annotated query parameter, validated before any handler runs;
  missing or non-numeric returns a 422.
- **`CommandAck`** — `{status, applied, request_id}`. Deliberately not the new state.
  `request_id` is set when the command is handed on to a pipeline; what answers or
  refuses it carries the same id.
- **`operation_id`** — an explicit, readable name per operation.
- Bodies are pydantic models (`ChannelSelection`, `AlarmNote`), so a malformed
  command returns a 422 instead of crashing a handler.

`ClientId`, `CommandAck` and `read_client_id` are defined once in `pswamp_web/wire.py`
and re-exported by `shared.py` for the scaffold apps (the import runs inward because
`pswamp_web` may not import the rest of the backend). `ClientId` is a string matching
`^\d{1,20}$`, and `read_client_id` applies that same pattern to sockets, so commands
and sockets cannot disagree about identity.

Every handler then does two things: change the right state, and get that change onto
the screen. The state lives in three different places, so there are three
arrangements.

**1. State in a module dict** — `reference_subapp`, and anything the subapp
scaffold generates. (An app over the server data architecture keeps its state in a
pipeline run instead; see `doc/server-data-architecture.md`.) The simplest case, needing no new plumbing: `SocketRegistry`
already addresses a client id and runs on this same event loop.

```
POST /api/reference-subapp/count/bump?client_id=42
  → get_state("42").bump()
  → logger.info("client %s: %s …", "42", "bump")
  → manager.send_to_client("42", state_message(model))   ← the push, from an HTTP handler
  → 200 CommandAck(applied="bump")
```

**2. State in the client's pipeline** — `islanding`. A client id reaches the hub, but
not the *push task*, which sits blocked on its queue inside a socket handler. So the
endpoint mutates and then wakes it:

```
POST /api/islanding/alarms/<uuid>/acknowledge?client_id=42
  → live_hub("42")                       ← 404 if this client has no pipeline
  → hub.alarms.annotate(uuid, …)         ← False for an unknown alarm → 404
  → _nudge("42")  → _offer(queue, None) for each of this client's open views
  → push task wakes, re-reads the hub, send_state()
  → 200 CommandAck(applied="acknowledge")
```

An operator action changes the alarm list, and no application publishes an event for
that. Without the nudge, the page would show the change only when the islanding
detector next produced a result — up to a second later. Measured round trip with it:
~1 ms.

**3. State on the connection itself** — `time_window`. A view's channel selection is
per-*connection*, living in a local variable inside the socket handler, and a command
arrives on no connection. `SessionRegistry` (`pswamp_web/sessions.py`) fixes that: the
handler publishes its `ClientState` for the life of the socket, and the command finds
it by client id.

```
POST /api/time-window/selection?client_id=42   {"channels": [5, 9]}
  → live_hub("42")
  → channels.sanitise(body.channels, tw.n_cols)   ← untrusted input, clamped
  → for each of this client's open views: selection = …, needs_full = True
  → 200 CommandAck(applied="select_channels (2)")
  → …no push here. The 10 Hz task sees needs_full on its next tick and sends
    the mode:"full" message by itself.
```

A client may hold several sessions for one endpoint — two tabs — so a command applies
to all of them: one browser is one viewer, and its views should agree. The registry
stores them in a **list**, not a set, because these are `eq=True` dataclasses and
Python makes those unhashable.

Two rules that hold across all three
--

- **A command never builds a pipeline.** `live_hub(client_id)` peeks; it never calls
  `REGISTRY.acquire`. Acquiring would spend four threads and ~30 MB against
  `MAX_PIPELINES` on a replay nobody is watching, and the POST has no socket to
  deliver to. No pipeline means a 404 — in practice, "you have no page open".
- **A socket that receives nothing still needs its receive loop.** Every WS handler
  ends in `while True: await ws.receive_text()`. Without a pending receive, nothing
  notices a closed socket until the next send, so an idle client lingers
  indefinitely — holding a pipeline slot, in the `pswamp_web` case.


The plain GETs
==

Two endpoints are neither commands nor pushed state, because what they return never
changes: the grid topology (`GET /api/grid/model`) and the channel catalogue
(`GET /api/time-window/channels`). A page fetches each once on mount via
`resolveApiUrl`, and the browser may cache it. Putting them on a socket would force
every consumer's hook to handle a second message shape just to receive something
static.


Error and refusal semantics
==

| condition | how it surfaces |
|---|---|
| missing, empty, negative or non-numeric `client_id`, or more than 20 digits | `422`, from FastAPI validation, before the handler |
| malformed command body | `422`, from the pydantic model |
| unknown sequence name | `422` naming the valid ones |
| unknown alarm uuid | `404` |
| command for a client with no pipeline | `404` |
| command for a client with no open view (`time-window`) | `404` |
| socket with an unusable client id | close `1008`, **before** accept — client stops retrying |
| socket when every pipeline is in use | accept, then close `1013` — client stops retrying |
| socket whose pipeline fails to start | accept, then close `1011`; the client retries |
| unknown path under `/api/` | real `404`, never the SPA shell (`SPAStaticFiles._NO_FALLBACK`) |

The numeric-string rule includes `"0"`, although the browser generates a positive
value.

All of which is the practical difference the two transports make: a rejected command
can say *why*, with a status code, in the access log and the Network tab.


Where the pieces live
==

| Path | What |
|---|---|
| `app/server-python/src/api_contract.py` | Document metadata, `WS_MESSAGE` validation/collection, the extension, schema merging |
| `app/server-python/tools/dump_openapi.py` | Imports the app, writes the document to a file |
| `uv run pswamp api generate` | Regenerates both artifacts; `--check` diffs instead |
| `doc/api/openapi.json` | The contract (generated, committed) |
| `app/client-web/src/api/schema.ts` | TypeScript (generated, committed, not linted) |
| `app/client-web/src/api/wire.ts` | Hand-written: `Wire[...]` and `ApiPaths` |
| `app/client-web/src/lib/commands.ts` | `postCommand`, typed against `ApiPaths` |
| `app/client-web/src/hooks/useServerSocket.ts` | The connection half, shared by every page |
| `app/client-web/src/lib/servers.ts` | `resolveApiUrl` / `resolveServerUrl` and the path consts |
| `app/server-python/src/server.py` | Wiring: mounts routers from `APPS`, composes lifespans |
| `app/server-python/src/shared.py` | `SocketRegistry`, and `ClientId` / `CommandAck` / `read_client_id` re-exported from `pswamp_web/wire.py` |
| `app/server-python/src/pswamp_web/wire.py` | Every p-SWAMP message model, and `send_state` |
| `app/server-python/src/pswamp_web/hub.py` | One pipeline per client, and the registry over them |


Implementation notes
==

**Shared wire primitives are defined inward.** `pswamp_web/` stays self-contained so
it can move with either Python consolidation path, but that rule only forbids imports
*out* of the package. `ClientId`, `CommandAck`, the client-id parser, `send_state` and
the logger therefore live inside it and `shared.py` re-exports them. Keep one
definition — duplicating them would make the code and the contract solve the same
identity twice.

**`openapi-typescript` declares a stale peer.** It wants `typescript@^5.x` while this
project runs 6, though it drives the TS 6 compiler API without complaint (we checked).
So `app/client-web/package.json` carries an `overrides` entry pointing that peer at
the project's own TypeScript, which keeps plain `npm install`/`npm ci` working with no
flags rather than pinning everything to `--legacy-peer-deps`. It costs one thing:
`uv run pswamp deps update` runs `npm-check-updates --peer`, which refuses to
bump TypeScript past 5 while the stale range stands, and says so. Drop the `overrides`
entry when upstream widens the range.
