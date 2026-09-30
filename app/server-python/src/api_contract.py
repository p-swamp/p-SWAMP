"""The published api contract: document metadata, and the socket half of it.

`server.py` mounts the apps; this module describes them. It is deliberately not
an app package -- it exposes no `router`, never appears in `APPS`, and holds no
domain logic -- so it sits beside `shared.py` rather than under it.

Why this exists
==

FastAPI already describes the *upstream* half of the api for free: every command
is a POST with an explicit `operation_id`, a pydantic body and a `CommandAck`
reply, so `/openapi.json` has always listed them. The *downstream* half was
invisible, because OpenAPI describes HTTP operations and every byte of state in
this system arrives over a WebSocket. The message models existed -- they are the
whole of `pswamp_web/wire.py` -- they were simply never published, so the web
client hand-maintained a TypeScript mirror of each one and a renamed field failed
at runtime rather than in any check.

This module closes that gap without a second spec format. It merges the socket
message schemas into `components.schemas` and records which channel carries which
under a vendor extension, so one document describes both directions and one
generator turns it into TypeScript.

How a package joins the contract
==

By exporting a name. `server.py` already discovers optional package features with
`getattr(module, "lifespan", None)`; socket messages work the same way::

    # pmu_test_streamer/__init__.py
    WS_MESSAGE = PmuStreamState

`ws_channels` walks the very `APPS` list `server.py` mounts and picks up whatever
each package exports under that name. There is no second registry to keep in
step, and `scripts/generate-new-subapp.sh` needs no extra anchor to patch -- a
scaffolded subapp is in the contract the moment it is generated, because its
template exports the name. An app with no socket (`pswamp_web/grid/`, which is
HTTP only) simply omits it.

Discovery by `getattr` has one failure mode, and `check_apps` closes it: an app
that serves a WebSocket and forgets the export used to drop out of the document
in silence. It now refuses to start.

The vendor extension
==

Channels land at the document root as `x-websocket-channels`::

    {"path": "/api/time-window/ws", "app": "time-window",
     "direction": "server-to-client",
     "message": {"$ref": "#/components/schemas/TimeWindowSlice"}}

An extension rather than AsyncAPI, deliberately: a second spec format would mean
a second generator, a second drift check and a second thing for another team to
learn, to describe seven one-way channels. `x-` keys are legal OpenAPI and every
generator ignores what it does not know, so the document stays valid and the
schemas -- which is what codegen actually consumes -- come through as ordinary
`components.schemas` entries.
"""

import json
from types import ModuleType
from typing import Literal, NamedTuple

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIWebSocketRoute
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema


class AppEntry(NamedTuple):
    """One backend api, as `server.py`'s `APPS` registry lists it.

    A record rather than a bare tuple because three things are keyed off the same
    app and they used to live in three shapes: the mount prefix (a string sliced
    back apart with `prefix[len("/api/"):]` wherever the url name was wanted), the
    module, and a description that sat in a *second* registry keyed by the slug.

    `slug` is the single spelling -- the url segment, the page route on the web
    client, and the tag in the published document. The package name is the same
    word with underscores, which is a Python identifier requirement rather than a
    choice (`reference_subapp` -> `/api/reference-subapp`).
    """

    slug: str
    module: ModuleType
    description: str = ""

    @property
    def prefix(self) -> str:
        """Where `server.py` mounts this app's router."""
        return f"/api/{self.slug}"


# --- document metadata -------------------------------------------------------

API_TITLE = "p-SWAMP api"

# Bump on a BREAKING contract change -- a removed or renamed field, a removed
# operation, a narrowed type. That is the point of it: the version is the one
# thing in the generated document a reviewer can look at to tell whether a diff
# is additive or not, and `doc/api/openapi.json` is committed so the bump shows
# up in the pull request beside the change that forced it.
#
# Not read from pyproject.toml on purpose: this project is `package = false`, so
# there is no installed distribution to read a version from, and the api's
# compatibility is not the same fact as the server's release number anyway.
API_VERSION = "2.0.0"

API_DESCRIPTION = """\
The api between the p-SWAMP web client and its state server.

**Two directions, two transports.** Anything a user triggers goes up as an HTTP
`POST` under `/api/<app>/`; everything the server has to say comes down a
WebSocket at `/api/<app>/ws`, which is downstream only. A command's reply is a
small `CommandAck`, never state, so state has exactly one path and there is no
ordering to reconcile between two of them.

**The operations below are therefore only half the api.** The socket half is
described by the `x-websocket-channels` extension at the root of this document,
whose message schemas are ordinary `components.schemas` entries — so a code
generator picks them up like any other model even though OpenAPI itself has no
notion of a socket.

**The first path segment after `/api/` is the routing key.** The server itself
holds no domain logic: it mounts one self-contained backend package under each
`/api/<app>` prefix, so `/api/pmu-test-streamer/...` is served by
`src/pmu_test_streamer/`, `/api/time-window/...` by
`src/pswamp_web/time_window/`, and so on for every tag listed below — the paths
a package declares are relative to its own prefix.
`/healthz` sits outside `/api` because it is the process's health rather than any
one app's, and everything else is the built web client, served from the same
origin with unknown paths falling back to its `index.html` so deep links work.

**Every request carries `?client_id=`**, a numeric string the browser resolves
once per profile and persists. It is the sharding key for all server state and
all of a browser's sockets must send the same one. It is *not* authentication and
does not pretend to be: supply someone else's id and you drive their session.

**The web client's types are generated from the API contract.**
`openapi-typescript` compiles it into `app/client-web/src/api/schema.ts`, which is
committed in git, and a page hook takes its downstream type from there rather
than hand-copying the Python model's fields — `Wire['ReferenceSubappState']` for
`/api/reference-subapp/ws`. Field names stay as the server sends them, snake_case
and all, all the way to the frontend components.

This document is generated from the server and committed at `doc/api/openapi.json`;
`scripts/error_check.sh` fails if the two disagree. See
`doc/the-client-server-api.md` for more detail.
"""


class HealthStatus(BaseModel):
    """Reply to `GET /healthz`, the liveness/readiness probe."""

    status: Literal["ok"] = "ok"


def openapi_tags(apps: list[AppEntry]) -> list[dict]:
    """Tag metadata for the document, in the order `APPS` mounts the apps.

    Purely descriptive: an app with no description costs nothing but a bare group
    heading in Swagger UI.
    """
    tags = []
    for app in apps:
        tag = {"name": app.slug}
        if app.description:
            tag["description"] = app.description
        tags.append(tag)
    return tags


# --- the socket half ---------------------------------------------------------


def ws_channels(apps: list[AppEntry]) -> list[tuple[str, str, type[BaseModel]]]:
    """`(channel path, app name, message model)` for every app with a socket.

    Discovered from the packages themselves via `WS_MESSAGE`, exactly as
    `server.py` discovers `lifespan`. Order follows `APPS`, so the generated
    document is stable across runs. An app that declares a socket without the
    export never reaches here -- `check_apps` refuses to start the server first.
    """
    channels = []
    for app in apps:
        message = getattr(app.module, "WS_MESSAGE", None)
        if message is None:
            continue
        channels.append((f"{app.prefix}/ws", app.slug, message))
    return channels


def check_apps(apps: list[AppEntry]) -> None:
    """Refuse to serve an app whose socket is missing from the contract.

    `WS_MESSAGE` is discovered by `getattr`, which is what keeps a package from
    having to register itself anywhere -- and what made forgetting it *silent*:
    the app dropped out of the published document, the page carried on working
    against a hand-written type, and nothing said the type safety was gone. The
    only way to notice was to read the generated file.

    So the one assumption behind the discovery is checked here instead: an app
    that serves a WebSocket publishes what it sends. Called from `install`, which
    `server.py` runs at import, so this fails at startup rather than in review.
    """
    for app in apps:
        if getattr(app.module, "WS_MESSAGE", None) is not None:
            continue
        sockets = [
            route.path
            for route in app.module.router.routes
            if isinstance(route, APIWebSocketRoute)
        ]
        if sockets:
            raise RuntimeError(
                f"{app.module.__name__} serves a WebSocket "
                f"({app.prefix}{sockets[0]}) but exports no WS_MESSAGE, so the "
                f"message it pushes would be absent from the published contract "
                f"and the web client could not generate a type for it. Add "
                f"`WS_MESSAGE = <TheModel>` to {app.module.__name__}/__init__.py "
                f"-- see src/reference_subapp/__init__.py."
            )


def _merge_schemas(components: dict, new: dict) -> None:
    """Add generated schemas to the document, refusing to redefine one.

    Some models are reachable from both halves of the api -- `Channel` sits under
    `GET /api/time-window/channels` *and* inside `TimeWindowSlice` -- so an
    overlap is normal and an identical redefinition is fine. A *differing* one is
    not: it would mean the document quietly disagreed with itself about a shape,
    which is the exact failure a published contract exists to prevent, and it
    would be invisible in review. Fail loudly instead.
    """
    for name, schema in new.items():
        existing = components.get(name)
        if existing is not None and existing != schema:
            raise RuntimeError(
                f"Two different schemas are both called {name!r}. Rename one of "
                f"the models, or give it an explicit "
                f"`model_config = ConfigDict(title=...)`.\n"
                f"  existing: {json.dumps(existing, sort_keys=True)[:400]}\n"
                f"  new:      {json.dumps(schema, sort_keys=True)[:400]}"
            )
        components[name] = schema


def inject_ws_channels(schema: dict, apps) -> dict:
    """Merge the socket message schemas into `schema` and list the channels.

    Mutates and returns the document.
    """
    channels = ws_channels(apps)
    if not channels:
        return schema

    # One call for ALL the models rather than one per model: they share nested
    # definitions (`Channel`, `Alarm`, `ReplayStatus`), and generating them
    # separately would emit each shared definition several times under
    # generator-chosen names instead of one `$ref` they all point at.
    #
    # "serialization" because these are outbound messages -- it is the shape
    # `model_dump_json` actually puts on the wire, which is what the client parses.
    models = [(model, "serialization") for _path, _app, model in channels]
    _keys, defs = models_json_schema(
        models,
        ref_template="#/components/schemas/{model}",
    )

    components = schema.setdefault("components", {}).setdefault("schemas", {})
    _merge_schemas(components, defs.get("$defs", {}))

    schema["x-websocket-channels"] = [
        {
            "path": path,
            "app": app,
            # Downstream only, everywhere. A socket that receives nothing still
            # has a receive loop, but only so a disconnect is noticed promptly --
            # nothing a client sends up one is ever read as a command.
            "direction": "server-to-client",
            "message": {"$ref": f"#/components/schemas/{model.__name__}"},
        }
        for path, app, model in channels
    ]
    return schema


# --- assembly ----------------------------------------------------------------


def build_document(app: FastAPI, apps: list[AppEntry]) -> dict:
    """The finished contract: what `/openapi.json` serves and what the committed
    `doc/api/openapi.json` holds. One function, so the two can never differ."""
    schema = get_openapi(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        routes=app.routes,
        tags=openapi_tags(apps),
        separate_input_output_schemas=app.separate_input_output_schemas,
    )
    inject_ws_channels(schema, apps)
    return schema


def install(app: FastAPI, apps: list[AppEntry]) -> None:
    """Make `app.openapi()` -- and so `/openapi.json`, `/docs` and `/redoc` --
    serve the document above rather than FastAPI's default.

    Also the point at which `check_apps` runs, i.e. at import of `server.py`:
    every app is mounted by then, and an app that would be missing from the
    document should stop the server rather than ship.
    """
    check_apps(apps)

    def openapi() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = build_document(app, apps)
        return app.openapi_schema

    app.openapi = openapi
