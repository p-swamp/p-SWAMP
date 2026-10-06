# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Drive the PMU test streamer end to end over the wire. Run by uv run pswamp test smoke.

    python tools/smoketest_pmu_test_streamer.py <base-url>

Proves the server data architecture is wired together wherever the server
runs (in-memory in one container, or Kafka and workers): the page's socket
opens on the paused recording, play brings frames and the frame-stats
module's results (from wherever that module is hosted), and the live source
refuses a seek with a 409. Exits 0 if every step passed.
"""

import asyncio
import json
import random
import sys
import urllib.error
import urllib.request

from websockets.asyncio.client import connect

API = "/api/pmu-test-streamer"
TIMEOUT = 10.0
failures: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"    \033[32m✓\033[0m {label}")
    else:
        print(f"    \033[31m✗\033[0m {label} -- {detail}")
        failures.append(label)


def post(base: str, path: str, client_id: str, body: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base}{API}{path}?client_id={client_id}",
        method="POST",
        data=json.dumps(body).encode() if body is not None else b"",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


async def until(ws, predicate) -> dict | None:
    """The first pushed state matching ``predicate``, or None after TIMEOUT."""
    async def read():
        while True:
            state = json.loads(await ws.recv())
            if predicate(state):
                return state

    try:
        return await asyncio.wait_for(read(), TIMEOUT)
    except TimeoutError:
        return None


async def main(base: str) -> int:
    client_id = str(random.randrange(10**9, 10**10))
    ws_base = base.replace("http", "ws", 1)
    print(f"\n  PMU test streamer (client_id={client_id})")
    async with connect(f"{ws_base}{API}/ws?client_id={client_id}") as ws:
        state = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT))
        player = state["player"]
        check("on connect: the recording, paused, showing its first frame",
              player["mode"] == "replay" and player["paused"] and state["frame_index"] == 0, player)
        check("the frame carries the CIM reference", state["frame"]["header"]["cimReferenceId"] is not None)
        status, ack = post(base, "/playback/speed", client_id, {"speed": 5})
        check("POST speed -> 200 {status, applied}", status == 200 and ack.get("applied") == "speed", (status, ack))
        post(base, "/playback/play", client_id)
        state = await until(ws, lambda s: s["stats"] is not None and not s["player"]["paused"])
        check("play: frames and the frame-stats module's results arrive",
              state is not None and state["stats"]["result"]["n_stations"] == 5, state)
        post(base, "/playback/source", client_id, {"name": "live"})
        state = await until(ws, lambda s: s["player"]["mode"] == "live" and s["frame"] is not None)
        check("switch to live: a frame stamped now", state is not None and state["frame_index"] is None, state)
        status, body = post(base, "/playback/seek", client_id, {"offset_s": 1})
        check("seek while live -> 409", status == 409, (status, body))
        post(base, "/playback/source", client_id, {"name": "sample"})
        state = await until(ws, lambda s: s["player"]["mode"] == "replay")
        check("back to the recording: paused", state is not None and state["player"]["paused"], state)
    status, _ = post(base, "/playback/play", "1")
    check("a command without an open page -> 404", status == 404, status)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1].rstrip("/"))))
