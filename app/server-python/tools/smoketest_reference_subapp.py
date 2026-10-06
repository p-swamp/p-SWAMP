# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Drive the Reference example app end to end. Driven by uv run pswamp test smoke.

    python tools/smoketest_reference_subapp.py <base-url>

This is the manual smoke test written down: open the socket, fire the REST
commands, and check that the counter coming back down the socket ends up where a
person clicking the buttons would expect it. Doing that proves routing, the
client id, the command path, the push path and the per-client state are all still
wired together -- which is why the Reference example is the app worth automating
rather than a p-SWAMP page.

It lives here rather than in the shell script because a WebSocket is the one part
bash has no way to speak. No new dependency: `websockets` is already in the
server's locked environment, pulled in by uvicorn[standard], and the POSTs go
through urllib, so this runs in the same `uv run --project app/server-python`
environment the api contract is generated in.

Deliberately NOT a browser test. It exercises the wire, not the UI -- nothing here
would notice a button that stopped calling its command. That is the gap a
Playwright test would close later; this closes the larger one first, at a fraction
of the cost.

Exits 0 if every step passed, 1 otherwise. Every step is reported, pass or fail,
so one run tells you everything that is broken rather than only the first thing.
"""

import asyncio
import json
import random
import sys
import urllib.error
import urllib.request

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

WS_PATH = "/api/reference-subapp/ws"
API_PATH = "/api/reference-subapp"

BUMPS = 3
# Every message here is pushed as a direct result of a command we just sent, so
# this is a "the server is wedged" timeout, not a pacing one.
RECV_TIMEOUT = 5.0
HTTP_TIMEOUT = 5.0

failures: list[str] = []


def ok(label: str) -> None:
    print(f"    \033[32m✓\033[0m {label}")


def bad(label: str) -> None:
    print(f"    \033[31m✗\033[0m {label}")
    failures.append(label)


def check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        ok(label)
    else:
        bad(f"{label}{f' -- {detail}' if detail else ''}")
    return condition


def new_client_id() -> str:
    """A fresh browser, in effect: state is per client id and never evicted, so a
    new one each run keeps repeated runs from seeing each other's counts."""
    return str(random.randrange(10**9, 10**10))


def post(base_url: str, path: str, client_id: str | None) -> tuple[int, dict]:
    """POST a command the way the web client does, returning (status, body).

    A status of 0 means the request never reached a server.
    """
    url = f"{base_url}{path}"
    if client_id is not None:
        url += f"?client_id={client_id}"
    request = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")
    except (urllib.error.URLError, OSError) as error:
        return 0, {"unreachable": str(error)}


def command(base_url: str, path: str, client_id: str, action: str) -> None:
    """Send one command and check its acknowledgement.

    A command answers with a small ack and never with state -- see the "commands
    up, state down" invariant in AGENTS.md. Asserting the ack's shape here is what
    would catch that being quietly undone.
    """
    status, body = post(base_url, path, client_id)
    check(
        f"POST {path} -> 200 {{status, applied}}",
        status == 200 and body.get("applied") == action and "status" in body,
        f"got {status} {body}",
    )


async def expect_state(ws, count: int, label: str) -> None:
    """Read the next pushed message and check the count it carries."""
    try:
        raw = await asyncio.wait_for(ws.recv(), RECV_TIMEOUT)
    except asyncio.TimeoutError:
        bad(f"{label}: no state pushed within {RECV_TIMEOUT:.0f}s")
        return
    message = json.loads(raw)
    check(
        f"{label}: count = {count}",
        message.get("type") == "state" and message.get("count") == count,
        f"got {message}",
    )


async def counter_flow(base_url: str, ws_url: str) -> None:
    """The manual test, step for step: connect, bump, verify, reset, verify."""
    client_id = new_client_id()
    print(f"\n  Counter flow (client_id={client_id})")

    async with connect(f"{ws_url}{WS_PATH}?client_id={client_id}") as ws:
        await expect_state(ws, 0, "on connect")

        for n in range(1, BUMPS + 1):
            command(base_url, f"{API_PATH}/count/bump", client_id, "bump")
            await expect_state(ws, n, f"after bump {n}")

        # A second browser starts at zero while the first sits at BUMPS: the
        # per-client state invariant, and the one thing a single-client run
        # cannot tell apart from a single global counter.
        other = new_client_id()
        async with connect(f"{ws_url}{WS_PATH}?client_id={other}") as ws_other:
            await expect_state(ws_other, 0, f"a second client (client_id={other})")

        command(base_url, f"{API_PATH}/count/reset", client_id, "reset")
        await expect_state(ws, 0, "after reset")


async def rejects_bad_callers(base_url: str, ws_url: str) -> None:
    """Both halves of the api must refuse a caller with no client id.

    They validate it the same way on purpose: `ClientId` (the query parameter)
    and `read_client_id` (the socket's) both apply `CLIENT_ID_PATTERN`, so a
    page's socket and its commands can never address different state. Checking
    only one half would miss the two drifting apart.

    All three are defined once, in `pswamp_web/wire.py`, and re-exported by
    `shared.py` -- which is where an app package imports them from, and the name
    to grep for.
    """
    print("\n  Caller validation")

    status, _ = post(base_url, f"{API_PATH}/count/bump", None)
    check("POST without client_id -> 422", status == 422, f"got {status}")

    # `InvalidStatus` specifically, not any error: the server closes before
    # accepting, which the handshake reports as an HTTP status. A connection
    # refused would satisfy a bare `except` and turn a dead server into a pass.
    try:
        async with connect(f"{ws_url}{WS_PATH}"):
            bad("WebSocket without client_id -> refused -- it was accepted")
    except InvalidStatus as error:
        ok(f"WebSocket without client_id -> refused ({error.response.status_code})")


async def phase(name, coro) -> None:
    """Run one group of steps, turning a crash into a reported failure.

    An unreachable server is the common case and raises out of the first connect;
    a traceback would bury the far more useful line above it saying /healthz never
    answered. Whatever the cause, the run continues to the next group.
    """
    try:
        await coro
    except Exception as error:
        bad(f"{name} could not run: {type(error).__name__}: {error}")


async def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <base-url>", file=sys.stderr)
        return 2
    base_url = argv[1].rstrip("/")
    ws_url = "ws" + base_url.removeprefix("http")

    await phase("counter flow", counter_flow(base_url, ws_url))
    await phase("caller validation", rejects_bad_callers(base_url, ws_url))

    if failures:
        print(f"\n  \033[31m{len(failures)} step(s) failed\033[0m")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv)))
