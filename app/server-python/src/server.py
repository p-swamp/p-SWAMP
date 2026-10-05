"""The one process entrypoint: assembles the app and routes to the app packages.

This module deliberately owns no domain logic. It does four things:

  1. mounts each app package's router under its own /api/<slug> prefix (APPS below),
  2. composes their lifespans into the single FastAPI lifespan,
  3. serves GET /healthz, the cheap liveness probe for Docker/k8s,
  4. serves the web client (the Vite build in static/) at / — same app, port, and
     origin as the api, so one image and one Service serve both.

Each app under src/<app>/ is a self-contained package exposing `router`, and
optionally `WS_MESSAGE` and `lifespan` (see src/reference_subapp/__init__.py).
Adding a backend api is one new package plus one entry in APPS; nothing else in
this file changes.

The server is entirely stateless in the persistence sense: there is no database
and nothing is written to disk. All state lives in the app packages' memory and is
gone when the process exits — a restart or redeploy resets every client.

Bind host/port come from the HOST/PORT env vars (default 127.0.0.1:8000) so the
container can publish on 0.0.0.0 without code changes; see Dockerfile.
"""

import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import RedirectResponse
from starlette.types import Scope

import api_contract
import pmu_test_streamer
import pswamp_web
import reference_subapp
import pswamp_web.app_status
import pswamp_web.grid
import pswamp_web.islanding
import pswamp_web.line_outage
import pswamp_web.phasors
import pswamp_web.time_window
from api_contract import AppEntry

# --- shared services --------------------------------------------------------
#
# Packages with no url surface of their own, whose lifespan must be running
# before any app package handles a request. Entered before everything in APPS and
# exited after it, so a websocket handler can assume its dependencies are up.
#
# pswamp_web is the one: it owns the registry of per-client PMU pipelines that
# its page packages all draw theirs from. Its lifespan starts no pipeline — those
# are built on a client's first connect and evicted when idle — it only binds the
# registry to this event loop and drains it on shutdown.

SERVICES = [pswamp_web]

# --- the app registry -------------------------------------------------------
#
# One AppEntry per backend api: its url slug, the package that serves it, and one
# line saying what it is (which becomes the group heading in /docs).
#
# The slug is the single spelling of an app's name. It is the url segment — the
# router is mounted at /api/<slug>, so the streamer's own "/ws" is served as
# /api/pmu-test-streamer/ws and several apps can each have a "ws" without
# colliding — and it is also the web client's route for the same app, so the two
# halves read the same. The package name is that word with underscores, which is
# a Python identifier requirement rather than a choice: pmu_test_streamer →
# /api/pmu-test-streamer.
#
# src/shared.py is NOT an app package and never appears here — it holds the
# domain-free helpers the packages import (see its docstring).

APPS = [
    AppEntry(
        "pmu-test-streamer",
        pmu_test_streamer,
        "Scaffold demo: replays sample PMU records line by line.",
    ),
    AppEntry(
        "app-status",
        pswamp_web.app_status,
        "Health and status of the running p-SWAMP monitoring applications. "
        "Only downstream status overview, no upstream commands to it yet.",
    ),
    AppEntry(
        "grid",
        pswamp_web.grid,
        "The static Nordic 44 topology. HTTP only — no socket.",
    ),
    AppEntry(
        "time-window",
        pswamp_web.time_window,
        "The measurement window: channel selection and the sample stream.",
    ),
    AppEntry(
        "islanding",
        pswamp_web.islanding,
        "Islanding detection results and the alarms derived from them.",
    ),
    AppEntry(
        "line-outage",
        pswamp_web.line_outage,
        "Detected line disconnect/reconnect events. "
        "Only downstream event log, no upstream commands to it yet.",
    ),
    AppEntry(
        "phasors",
        pswamp_web.phasors,
        "Voltage phasors, referred to a rotating reference. "
        "Only downstream snapshots, no upstream commands to it yet.",
    ),
    AppEntry(
        "reference-subapp",
        reference_subapp,
        "The reference example: a per-client counter over the whole stack.",
    ),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run every app package's own lifespan for as long as the process is up.

    An app package may need startup/shutdown work — the PMU test streamer runs
    its playback ticker task that way. AsyncExitStack composes however many there
    are into this one context, and unwinds them in reverse on shutdown, so no
    package has to know about any other. `lifespan` is optional: a package with only
    request handlers just omits it.
    """
    async with AsyncExitStack() as stack:
        for module in SERVICES:
            await stack.enter_async_context(module.lifespan(app))
        for entry in APPS:
            app_lifespan = getattr(entry.module, "lifespan", None)
            if app_lifespan is not None:
                await stack.enter_async_context(app_lifespan(app))
        yield


# Title, version and per-app tag descriptions come from api_contract.py, which
# also owns the socket half of the document -- see `install` at the bottom of this
# file. Without them the api would publish as "FastAPI 0.1.0", which tells a
# consuming team nothing and makes a breaking change undetectable.
app = FastAPI(
    lifespan=lifespan,
    title=api_contract.API_TITLE,
    version=api_contract.API_VERSION,
    description=api_contract.API_DESCRIPTION,
    openapi_tags=api_contract.openapi_tags(APPS),
)

# In the shipped image the web client is served from this same origin, so none of
# this applies. In local dev it is not: the client runs on the Vite dev server
# and talks to this process on another port.
#
# That was invisible for as long as the client only opened WebSockets, which are
# not subject to the same-origin policy. The moment a page fetched something over
# plain HTTP — the grid topology, the channel catalogue — the browser began
# silently discarding the responses, and the affected component sat waiting for
# data that had in fact arrived.
#
# Wide open, and it now needs a fuller justification than it did: this server no
# longer only reads. Every operator action -- play, pause, pick a channel,
# acknowledge an alarm -- is a POST under /api/<app>/, so a page on any origin can
# drive a client's replay if it knows that client's id.
#
# It stays open anyway, deliberately, because of what those mutations actually
# touch: a per-client replay of a committed sample recording, with no auth, no
# secrets, and nothing persisted -- a reload of the page undoes any of it. The
# client id is not a credential and the server says so (see hub.read_client_id).
#
# What WOULD change this: anything real behind an endpoint. Live PMU data, a
# store that outlives the process, or any notion of a user. Narrow it to the dev
# origins then, and note that nothing here depends on the wildcard today -- both
# dev (through the Vite proxy) and production (served by this process) are
# same-origin, so CORS is not exercised at all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", operation_id="healthz")
async def healthz() -> api_contract.HealthStatus:
    """Liveness probe for Docker/k8s, and the compose healthcheck. Cheap and
    side-effect-free: the server has no external dependencies, so "the process is
    up and serving" is the whole health story — there is nothing a separate
    readiness probe could usefully check. Deliberately at the root rather than
    under /api: it is the process's health, not any one app's."""
    return api_contract.HealthStatus()


for _app in APPS:
    # Tagged with the app's own url slug, so the generated api description groups
    # each app's operations together rather than listing them flat. Taken from
    # the entry rather than written out, so a new entry in APPS above needs
    # nothing here.
    app.include_router(_app.module.router, prefix=_app.prefix, tags=[_app.slug])


# --- the published api contract ---------------------------------------------
#
# Replaces FastAPI's generated document with the one api_contract.py builds: the
# same operations, plus the WebSocket message schemas, which OpenAPI has no notion
# of and which are the bulk of what the web client needs typed. Must run AFTER the
# include_router loop above, or the document would describe an empty api.
#
# /openapi.json, /docs and /redoc all serve this, and it is the same function
# scripts/generate-api-contract.sh dumps to doc/api/openapi.json -- so the served
# document and the committed one cannot drift.

api_contract.install(app, APPS)


# --- web client assets ------------------------------------------------------
#
# Serve the web client from this same app/port/origin as the api, so the single
# node (and single k8s Service) serves both — no second service, no CORS.
#
# static/ is the Vite build output (index.html + favicon/icons + hashed files
# under assets/), baked into the image by the Dockerfile's web-build stage. The
# mount is guarded on the dir existing so the api-only paths still boot without it
# — i.e. `uv run src/server.py` from app/server-python/ for quick backend dev (the
# web client is run separately with hot reload via
# scripts/start-local-hotloaded-pswamp-web-client.sh). It's registered AFTER
# /healthz and the routers above because a mount at "/" is greedy and would shadow
# them — so must any api route added later.


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html on a 404, so client-side routes
    (and a hard refresh / deep link onto one) resolve to the SPA shell instead of
    404ing. Requests for real files — hashed assets, favicon — still hit those
    first.

    Two prefixes keep their real 404 instead of the shell: a missing file under
    assets/ (a bad hashed-asset URL should fail loudly, not return HTML with the
    wrong content type) and anything under api/ (a wrong or removed endpoint must
    look wrong to a JSON caller, and an api 404 is never a navigation route).
    Everything else, i.e. the client's own routes, falls through to the shell.

    A route asked for with a trailing slash (/phasors/) is redirected to the bare
    route instead of being handed the shell. The shell references its assets
    relatively (vite.config.ts, `base: './'`), so served at /phasors/ it would
    look for them under /phasors/assets/, get the shell back as text/html, and
    render a blank page. The redirect is itself relative (`../phasors`): the
    server does not know the prefix a reverse proxy mounts it under, and the
    browser resolves a relative Location against the url it actually asked for.

    It also sets Cache-Control, which StaticFiles does not. Without it a browser
    may apply heuristic freshness and serve the shell from cache unvalidated —
    and since asset filenames are content-hashed, a cached shell pins the previous
    build's assets, so the whole old client is reassembled from cache with no
    requests made. The deploy looks stale when it isn't. Only the shipped image
    is affected; Vite's dev server sends no-cache itself.

    So: the shell is a mutable name and must revalidate (`no-cache` means "ask
    first", not "don't store" — the ETag makes that a 304); everything under
    assets/ is immutable and never needs revalidating.
    """

    _NO_FALLBACK = ("assets/", "api/")

    _IMMUTABLE = "public, max-age=31536000, immutable"
    _REVALIDATE = "no-cache"

    async def get_response(self, path: str, scope: Scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith(self._NO_FALLBACK):
                redirect = self._bare_route_redirect(scope)
                if redirect is not None:
                    return redirect
                response = await super().get_response("index.html", scope)
                response.headers["cache-control"] = self._REVALIDATE
                return response
            raise

        # favicon.svg and index.html change in place, so only assets/ is cacheable.
        cacheable = path.startswith("assets/") and response.status_code == 200
        response.headers["cache-control"] = (
            self._IMMUTABLE if cacheable else self._REVALIDATE
        )
        return response

    @staticmethod
    def _bare_route_redirect(scope: Scope) -> RedirectResponse | None:
        """A redirect to the same route without its trailing slash(es), or None
        if the request has none. `path` as get_response receives it is already
        normalised, so the slash is only visible on the scope."""
        requested = scope["path"]
        bare = requested.rstrip("/")
        if not bare or bare == requested:
            return None
        # One `..` per stripped slash: each is a directory level of the document.
        target = "../" * (len(requested) - len(bare)) + quote(
            bare.rsplit("/", 1)[-1], safe=""
        )
        if scope.get("query_string"):
            target += "?" + scope["query_string"].decode("latin-1")
        return RedirectResponse(target, status_code=307)


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    # Default to loopback for local dev; the container sets HOST=0.0.0.0.
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
