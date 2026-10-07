# Subapp and module templates

What the generators copy into a new app. Edit these to change what every new
page/api starts life as; the generator (`../generate.py`) only derives names and patches the
registries. Two sets:

- `subapp/`, for `uv run pswamp new subapp`: a per-client counter, like the
  checked-in reference subapp (`app/server-python/src/reference_subapp/`).
- `module/`, for `uv run pswamp new module`: a module project over the
  core pipeline, its messages, its pipeline and its web API, a page showing its latest
  result, and unit tests. The project joins the workspace, the server's
  dependencies and the lock, and the module and its pipeline file are added to the
  module-worker in compose and k8s. `doc/module-cookbook.md` walks through it.

In each set:

- `server-python/` → `app/server-python/src/<pkg>/`
- `client-web/` → `app/client-web/src/pages/<slug>/`

The module set has seven more folders. What the module publishes goes to the
models (`models/`, pydantic only), where the module, its web API and anyone
else import it from. The module is a project of its own, `modules/<slug>/`,
which depends on the core and the models only, so nothing rendered there may
import from the web backend; only the web API goes into the server. Its
pipeline is a TOML file in `pipelines/` at the repo root, naming the module by
its entry point:

- `models/` → `models/src/pswamp_models/<pkg>/`
- `module-project/` → `modules/<slug>/` (`pyproject.toml` with the
  `pswamp.modules` entry point, `README.md`)
- `module/` → `modules/<slug>/src/pswamp_modules/<pkg>/` (no
  `src/pswamp_modules/__init__.py`: the package is a PEP 420 namespace portion)
- `module-tests/` → `modules/<slug>/tests/`
- `module-examples/` → `modules/<slug>/examples/` (a script running the module
  with no server)
- `pipeline/` → `pipelines/` (`<slug>.toml`)
- `tests/` → `app/server-python/tests/`

A module's `tests/` is not a package, and runs in one pytest session with every
other test folder, so its test file is named after the module
(`test___PKG___module.py`) rather than `test_module.py`; the generator refuses
a name whose test file exists in any test folder.

What the generator writes is then yours: change it freely. The rest of this file
describes the `subapp` set; the module set follows the same rules.

**This file is where the scaffolding is explained.** The templates themselves
carry only the comments a real subapp would carry, because every generated subapp
inherits its comments verbatim — doc *about the scaffolding* would then be copied
into a dozen apps it does not describe, ageing separately in each. Put new
guidance about the templates here, and keep it out of the templates.

For the same reason this file does not re-explain the client/server seam the
templates are an instance of. That is `doc/the-client-server-api.md`, and it is
the authority wherever the two overlap; what is here is the template-editing
layer on top of it.

## Rendering

Every template is named `<filename>.template`, and the suffix is stripped when
it is rendered — `use__NAME__Socket.ts.template` becomes
`useGridOverviewSocket.ts`. That suffix is not decoration: it disables IDE error checking etc.

Both the file contents and the file *names* are rendered, so a template can be
called `use__NAME__Socket.ts.template`. The tokens, for the example name
`grid-overview` with nav label `Grid Overview`:

| Token | Becomes | Used for |
|---|---|---|
| `__SLUG__` | `grid-overview` | the URL, the page folder, the `/api/<app>` prefix |
| `__PKG__` | `grid_overview` | the Python package |
| `__NAME__` | `GridOverview` | the React component, the hook, the model class |
| `__WS_PATH_CONST__` | `GRID_OVERVIEW_WS_PATH` | the ws path const in `lib/servers.ts` |
| `__API_PATH_CONST__` | `GRID_OVERVIEW_API_PATH` | the REST prefix const, same file |
| `__UPPER__` | `GRID_OVERVIEW` | the environment variable prefix (`<APP>_DATA_CLIENTS`) |
| `__LABEL__` | `Grid Overview` | the nav entry and page title |

The rendered Python has to pass `uv run pswamp check` — pyflakes lint plus a
syntax compile — so avoid unused imports or names. Line length is no longer
enforced (formatting and pycodestyle were dropped from the gate), but the
templates still keep lines short for readability, so prefer a token at the end of
its line. The prose here is written to the generator's 32-character name cap; the one
line that stretches at the top of that range is `state_message`'s signature, which
carries `__NAME__` twice.

## What the generated subapp is

A per-client counter to bump and reset: the smallest thing that proves the
wiring, and a placeholder to replace rather than a stub to fill in.

It exercises **both transports**, because a subapp uses two: state comes **down**
over the WebSocket, commands go **up** as POSTs. `POST /api/<slug>/count/bump`
changes the count, the socket carries the new value back — so a new subapp starts
with the convention already wired rather than as something to remember. Keep both
halves when you replace the counter.

`doc/the-client-server-api.md` is the account of *why* the seam is shaped this
way, and its "Common tasks" section is the recipe for changing it — including
"run the generator on a throwaway name and read the diff", which shows every moving
part at once. What follows here is only what a template editor needs on top of
that.

The conventions the rendered code embodies, each of which the api doc explains
and none of which should be edited away:

- **One POST per operation**, rather than one endpoint taking an action name —
  and **every one carries an explicit `operation_id`**, spelled `<app>_<verb>`
  (`__PKG___bump` renders as `grid_overview_bump`). A generated client calls that
  name, so renaming a handler must never rename someone's method. Add a command
  to the template and it needs one too.
- **A command never answers with state.** It returns a `CommandAck`; the
  resulting state arrives on the socket like any other change.
- **`ClientId` and `CommandAck` come from `shared.py`**, so every app declares
  its caller and its reply the same way. That import is right because the
  templates render a standalone app under `src/<pkg>/`; inside `pswamp_web/` the
  same two names come from `..wire` instead, and a template copied in there has
  to be re-pointed.
- **The socket's receive loop is not vestigial.** Without a pending receive, a
  closed socket is only noticed on the next send, so an idle client lingers.
- **Controls are disabled until connected.** The POSTs would in fact reach the
  server without a socket, but the result comes back *on* the socket, so a click
  with none open would appear to do nothing.

## The api contract

A new subapp is in the published contract automatically, and there is **no
registry to add it to** — the mechanism is the `WS_MESSAGE = __NAME__State` line
in the generated `__init__.py`, and `doc/the-client-server-api.md`, under "How a
package joins the contract", is the full account of it. What it means here is
that `Wire['__NAME__State']` in the rendered hook is generated from the rendered
Python model, so the two cannot drift.

Four things follow when editing these templates:

- **Keep `state_message()` returning a pydantic model**, and keep `__NAME__State`
  a declared model rather than a loose dict. Return a bare dict and the app
  silently drops out of the contract — the page still works, and the type safety
  is gone with nothing to say so.
- **The prose in the Python templates is not all comments.** Endpoint docstrings
  become operation descriptions and `Field(description=...)` becomes the schema
  description, so both are published in `doc/api/openapi.json` and rendered in
  `/docs` — for every subapp ever generated. Write them as api text, addressed to
  someone reading the api and not to someone editing these templates: a docstring
  here that explains the scaffolding ends up in the contract, which is where this
  README's own url used to appear. (The counter's `"This client's count. Replace
  with real state."` is the one deliberate exception, a placeholder that says so.)
- **A command that grows a body takes a pydantic model**, and a plain `GET` added
  beside these declares a response model — a bare `-> dict` publishes as an
  untyped `object` and leaves the client casting an implicitly-`any` body.
- **`pswamp new` regenerates the contract before it runs
  `pswamp check`**, because the rendered hook imports a type that does not
  exist until it does. Commit `doc/api/openapi.json` and
  `app/client-web/src/api/schema.ts` along with the generated subapp.

## Two details that look like omissions

- **The state message does not echo the client id back.** The web client already
  knows who it is — one id per browser, resolved once in `src/lib/clientId.ts`
  and shown in the layout footer — so sending it would only be a second copy to
  keep in step. The id still keys `states` server-side; it is just not page data.
- **The hook does not map the message to anything.** It types it with the
  generated `Wire['<Name>State']` and hands it to the page, field names and all.
  Hooks used to rename every field into camelCase; that is ~150 lines the repo no
  longer has, and — more to the point — it failed silently, since a `useMemo`
  that omits a newly added field type-checks fine and the field just never
  appears. Derive things in a hook by all means (the grid monitor's line-outage
  hook does); don't rename.
