# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""One level of the PMU test streamer load test. Run by uv run pswamp test load.

    python tools/loadtest_pmu_test_streamer.py <base-url> --clients N --out result.json
        [--steady 60] [--speed 1] [--source remote]

N clients, each with its own client id and so its own run, do what a person
on the page does: open the page's two sockets (the streamer's and the error
tray's), press a source, press play and watch. Midway through the steady window
each one seeks to a random instant (playing on) and asks for a one-second range
summary. At the end each one pauses, so its run costs nothing while it waits
for idle eviction, then disconnects.

Measured over the steady window, per client: distinct frames per second, stream
time per wall second, stalls (more than three frame intervals between two
frames), the share of state messages whose frame stats are about their frame,
bytes per message, the latency of each command (its POST until the socket shows
its effect) and every error-tray notice. Beside them: ``/healthz`` round trips
every 250 ms (the server's event loop), and this process's CPU and loop lag, so
a driver that cannot keep up is visible. The thresholds live in the CLI
(tools/src/pswamp_tools/load.py); this writes the numbers to ``--out``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from datetime import datetime, timedelta, timezone

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

API = "/api/pmu-test-streamer"
#: Frame intervals between two frames that make a stall.
STALL_INTERVALS = 3
#: What the stub's own outages put on the tray; anything else is unexpected.
GAP_NOTICE = "no data from"


def instant(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text.replace("Z", "+00:00"))


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(q / 100 * (len(ordered) - 1))))]


class Client:
    def __init__(self, client_id: str, base: str, http: httpx.AsyncClient, speed: float, source: str) -> None:
        self.id, self.base, self.http, self.speed, self.source = client_id, base, http, speed, source
        #: Per state message: (received, frame timestamp, stats timestamp, bytes, data rate)
        self.messages: list[tuple[float, str | None, str | None, int, float | None]] = []
        self.notices: list[dict] = []
        self.latency: dict[str, float | None] = {}
        self.seek_window: tuple[float, float] | None = None
        self.failure: str | None = None
        self.close_code: int | None = None
        self.last: dict | None = None
        self._waiters: list[tuple] = []

    # -- the two sockets ----------------------------------------------------------------

    async def read_state(self, ws) -> None:
        try:
            async for raw in ws:
                now = time.monotonic()
                message = json.loads(raw)
                self.last = message
                frame, stats = message.get("frame"), message.get("stats")
                rate = frame["header"].get("data_rate") if frame else None
                self.messages.append((now, frame and frame["timestamp"], stats and stats["timestamp"], len(raw), rate))
                self._wake(now)
        except ConnectionClosed as closed:
            self.close_code = closed.rcvd.code if closed.rcvd else None
            self._wake(time.monotonic())

    async def read_notices(self, ws) -> None:
        try:
            async for raw in ws:
                notice = json.loads(raw)
                self.notices.append(
                    {k: notice.get(k) for k in ("source", "message", "detail", "request_id")} | {"at": time.monotonic()}
                )
                self._wake(time.monotonic())
        except ConnectionClosed:
            pass

    def _wake(self, now: float) -> None:
        for waiter in list(self._waiters):
            test, future = waiter
            if not future.done() and test():
                future.set_result(now)
                self._waiters.remove(waiter)

    def until(self, test, timeout: float):
        """When ``test()`` first holds (``time.monotonic``), checked on every message."""
        future = asyncio.get_running_loop().create_future()
        if test():
            future.set_result(time.monotonic())
        else:
            self._waiters.append((test, future))
        return asyncio.wait_for(future, timeout)

    def player(self) -> dict:
        return (self.last or {}).get("player") or {}

    async def post(self, path: str, body: dict | None = None) -> dict:
        response = await self.http.post(f"{self.base}{API}{path}", params={"client_id": self.id}, json=body)
        if response.status_code != 200:
            raise RuntimeError(f"POST {path}: HTTP {response.status_code} {response.text[:200]}")
        return response.json()

    async def timed(self, name: str, path: str, body: dict | None, test, timeout: float = 30.0) -> None:
        start = time.monotonic()
        await self.post(path, body)
        self.latency[name] = await self.until(test, timeout) - start

    # -- the session ----------------------------------------------------------------------

    async def run(self, ready: asyncio.Event, steady: asyncio.Future, window: float, stop: asyncio.Event) -> None:
        readers: list[asyncio.Task] = []
        try:
            ws_base = self.base.replace("http", "ws", 1)
            start = time.monotonic()
            tray = await connect(f"{ws_base}/api/errors/ws?client_id={self.id}", max_size=None, open_timeout=60)
            readers.append(asyncio.create_task(self.read_notices(tray)))
            ws = await connect(f"{ws_base}{API}/ws?client_id={self.id}", max_size=None, open_timeout=60)
            readers.append(asyncio.create_task(self.read_state(ws)))
            try:
                self.latency["connect"] = await self.until(lambda: self.last is not None or self.close_code, 60) - start
            except TimeoutError:
                raise RuntimeError("no state message within 60 s") from None
            if self.last is None:
                raise RuntimeError(f"refused: socket closed with {self.close_code}")
            switched = lambda: self.player().get("source") == self.source and (self.last or {}).get("frame") is not None  # noqa: E731
            await self.timed("switch", "/playback/source", {"name": self.source}, switched)
            if self.speed != 1:
                await self.timed("speed", "/playback/speed", {"speed": self.speed}, lambda: self.player().get("speed") == self.speed)
            await self.timed("play", "/playback/play", None, lambda: self.player().get("paused") is False)
            ready.set()

            # Midway: a click on the timeline, then a summary of the second after it.
            started = await steady
            await asyncio.sleep(max(0.0, started + window * random.uniform(0.35, 0.6) - time.monotonic()))
            if stop.is_set():
                return
            await self.seek_and_summarize()
            await stop.wait()
        except Exception as error:  # noqa: BLE001 -- one client's failure is a result, not a crash
            self.failure = f"{type(error).__name__}: {error}"
            ready.set()
        finally:
            await stop.wait()
            if self.failure is None:
                try:
                    await self.post("/playback/pause")  # an idle run then costs nothing until it is evicted
                except Exception:  # noqa: BLE001
                    pass
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)

    async def seek_and_summarize(self) -> None:
        player = self.player()
        first, end = instant(player["coverage_start"]), instant(player["coverage_end"])
        span = (end - first).total_seconds()
        at = first + timedelta(seconds=random.uniform(min(3600, span / 4), max(span / 2, span - 3600)))
        sent = time.monotonic()

        def landed() -> bool:
            """The first frame at or after the instant is shown (an outage moves it on)."""
            frame = (self.last or {}).get("frame")
            return frame is not None and instant(frame["timestamp"]) >= at

        try:
            await self.timed("seek", "/playback/seek", {"at": at.isoformat(), "play": True}, landed)
        except TimeoutError:
            self.latency["seek"] = None
        self.seek_window = (sent, time.monotonic() + 3.0)
        if self.latency["seek"] is None:
            return
        cursor = instant(self.last["frame"]["timestamp"])
        start = time.monotonic()
        ack = await self.post(
            "/summary",
            {"source": self.source, "start": cursor.isoformat(), "end": (cursor + timedelta(seconds=1)).isoformat()},
        )
        asked = ack["request_id"]

        def answered() -> bool:
            summary = (self.last or {}).get("summary") or {}
            return summary.get("request_id") == asked or any(n["request_id"] == asked for n in self.notices)

        try:
            self.latency["summary"] = await self.until(answered, 60) - start
        except TimeoutError:
            self.latency["summary"] = None

    # -- the numbers ----------------------------------------------------------------------

    def report(self, a: float, b: float) -> dict:
        """Over the steady window [a, b), less the seek and 3 s after it."""
        cut = self.seek_window
        rows = [m for m in self.messages if a <= m[0] < b and not (cut and cut[0] <= m[0] < cut[1])]
        span = (b - a) - (max(0.0, min(b, cut[1]) - max(a, cut[0])) if cut else 0.0)
        rate = next((m[4] for m in rows if m[4]), None)
        interval = 1 / rate if rate else None
        seen: set[str] = set()
        frames, gaps, lags = 0, [], []
        progress, missed, stalls = 0.0, 0, 0
        last_ts = last_at = None
        for at, frame_ts, stats_ts, _, _ in rows:
            if frame_ts is None or frame_ts in seen:
                continue
            seen.add(frame_ts)
            frames += 1
            ts = instant(frame_ts)
            if stats_ts and interval:
                lags.append((ts - instant(stats_ts)).total_seconds() / interval)
            if last_ts is not None:
                step = (ts - last_ts).total_seconds()
                if 0 < step < 1.0:  # not a seek, not an outage crossed
                    progress += step
                    gap = at - last_at
                    gaps.append(gap * 1000)
                    if interval:
                        missed += max(0, round(step / interval) - 1)
                        stalls += gap > STALL_INTERVALS * interval / self.speed
            last_ts, last_at = ts, at
        return {
            "data_rate": rate,
            "messages_per_s": len(rows) / span if span > 0 else None,
            "frames_per_s": frames / span if span > 0 else None,
            "progress": progress / span if span > 0 else None,
            "missed_frames": missed,
            "stalls": stalls,
            "stall_share": stalls / len(gaps) if gaps else None,
            "gap_p99_ms": percentile(gaps, 99),
            "gap_max_ms": max(gaps) if gaps else None,
            "stats_share": sum(1 for m in rows if m[2] is not None) / len(rows) if rows else None,
            "stats_lag_frames": percentile(lags, 50),
            "bytes_per_message": statistics.mean(m[3] for m in rows) if rows else None,
        }


async def probe_health(base: str, stop: asyncio.Event, out: list) -> None:
    async with httpx.AsyncClient(timeout=10) as http:
        while not stop.is_set():
            start = time.monotonic()
            try:
                answered = (await http.get(f"{base}/healthz")).status_code == 200
            except Exception:  # noqa: BLE001
                answered = False
            out.append((start, (time.monotonic() - start) * 1000, answered))
            await asyncio.sleep(0.25)


async def probe_loop(stop: asyncio.Event, out: list) -> None:
    while not stop.is_set():
        start = time.monotonic()
        await asyncio.sleep(0.1)
        out.append((start, (time.monotonic() - start - 0.1) * 1000))


def largest(values) -> float | None:
    values = [v for v in values if v is not None]
    return max(values) if values else None


def smallest(values) -> float | None:
    values = [v for v in values if v is not None]
    return min(values) if values else None


def middle(values) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base")
    parser.add_argument("--clients", type=int, required=True)
    parser.add_argument("--steady", type=float, default=60.0)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--source", default="remote")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    first_id = random.randrange(10**12, 9 * 10**12)
    stop = asyncio.Event()
    steady: asyncio.Future = asyncio.get_running_loop().create_future()
    health: list = []
    lag: list = []
    limits = httpx.Limits(max_connections=max(100, 2 * args.clients), max_keepalive_connections=max(100, 2 * args.clients))
    async with httpx.AsyncClient(timeout=60, limits=limits) as http:
        clients = [Client(str(first_id + i), base, http, args.speed, args.source) for i in range(args.clients)]
        readies = [asyncio.Event() for _ in clients]
        probes = [asyncio.create_task(probe_health(base, stop, health)), asyncio.create_task(probe_loop(stop, lag))]
        began = time.monotonic()
        cpu_before = time.process_time()
        sessions = [asyncio.create_task(c.run(r, steady, args.steady, stop)) for c, r in zip(clients, readies)]
        try:
            await asyncio.wait_for(asyncio.gather(*(r.wait() for r in readies)), 120)
        except TimeoutError:
            pass
        setup = time.monotonic() - began
        served = sum(1 for c in clients if c.failure is None)
        print(f"    {served}/{args.clients} clients playing after {setup:.1f} s; steady for {args.steady:.0f} s…", flush=True)
        await asyncio.sleep(2.0)  # the first frames settle
        a, wall_a = time.monotonic(), datetime.now(timezone.utc)
        steady.set_result(a)
        await asyncio.sleep(args.steady)
        b, wall_b = time.monotonic(), datetime.now(timezone.utc)
        cpu_used = time.process_time() - cpu_before
        stop.set()
        await asyncio.gather(*sessions, return_exceptions=True)
        for probe in probes:
            probe.cancel()

    per_client = []
    for c in clients:
        row = {"client_id": c.id, "failure": c.failure, "close_code": c.close_code, "latency": c.latency}
        row |= c.report(a, b) if c.failure is None else {}
        row["notices"] = [{k: n[k] for k in ("source", "message", "request_id")} for n in c.notices]
        per_client.append(row)
    ok = [r for r in per_client if r["failure"] is None]
    in_window = [h for h in health if a <= h[0] < b]
    lags = [x[1] for x in lag if a <= x[0] < b]
    notices: dict[str, int] = {}
    unexpected: dict[str, int] = {}
    for row in per_client:
        for n in row["notices"]:
            key = f"{n['source']}: {n['message']}"[:160]
            notices[key] = notices.get(key, 0) + 1
            if not (n["message"] or "").startswith(GAP_NOTICE):
                unexpected[key] = unexpected.get(key, 0) + 1
    rates = [r["data_rate"] for r in ok if r.get("data_rate")]

    def latency(name: str, pick) -> float | None:
        return pick(r["latency"].get(name) for r in ok)

    summary = {
        "clients": args.clients,
        "served": len(ok),
        "speed": args.speed,
        "source": args.source,
        "data_rate": middle(rates),
        "steady_s": b - a,
        "steady_utc": [wall_a.isoformat(), wall_b.isoformat()],
        "setup_s": setup,
        "failures": sorted({r["failure"][:200] for r in per_client if r["failure"]}),
        "close_codes": sorted({r["close_code"] for r in per_client if r["close_code"]}),
        "connect_s_max": latency("connect", largest),
        "switch_s_p50": latency("switch", middle),
        "switch_s_max": latency("switch", largest),
        "play_s_max": latency("play", largest),
        "seek_s_p50": latency("seek", middle),
        "seek_s_max": latency("seek", largest),
        "seek_timeouts": sum(1 for r in ok if "seek" in r["latency"] and r["latency"]["seek"] is None),
        "summary_s_max": latency("summary", largest),
        "summary_timeouts": sum(1 for r in ok if "summary" in r["latency"] and r["latency"]["summary"] is None),
        "frames_per_s_min": smallest(r.get("frames_per_s") for r in ok),
        "frames_per_s_p50": middle(r.get("frames_per_s") for r in ok),
        "progress_min": smallest(r.get("progress") for r in ok),
        "messages_per_s_p50": middle(r.get("messages_per_s") for r in ok),
        "missed_frames": sum(r.get("missed_frames", 0) for r in ok),
        "stalls": sum(r.get("stalls", 0) for r in ok),
        "stall_share_max": largest(r.get("stall_share") for r in ok),
        "gap_max_ms": largest(r.get("gap_max_ms") for r in ok),
        "stats_share_min": smallest(r.get("stats_share") for r in ok),
        "bytes_per_message": middle(r.get("bytes_per_message") for r in ok),
        "healthz_ms_p50": percentile([h[1] for h in in_window], 50),
        "healthz_ms_p99": percentile([h[1] for h in in_window], 99),
        "healthz_failed": sum(1 for h in in_window if not h[2]),
        "driver_cpu": cpu_used / (b - began),
        "driver_lag_ms_p99": percentile(lags, 99),
        "notices": notices,
        "unexpected_notices": unexpected,
    }
    with open(args.out, "w", encoding="utf-8") as out:
        json.dump({"summary": summary, "clients": per_client}, out, indent=1, default=str)


if __name__ == "__main__":
    asyncio.run(main())
