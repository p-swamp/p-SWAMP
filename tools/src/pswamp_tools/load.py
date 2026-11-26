"""The PMU test streamer load test: levels of concurrent clients, each with its own run, against thresholds.

Each level is one run of app/server-python/tools/loadtest_pmu_test_streamer.py
in the server's environment, which writes its numbers as JSON; this side owns
the server's lifecycle (as the smoke test does), samples the compose
containers' CPU and memory during each steady window, checks the numbers
against ``Thresholds`` and reports. Without a URL it owns the server: every
p-swamp container is removed, the compose stack built and started with the
streamer's run cap (``PMU_TEST_STREAMER_MAX_RUNS``) raised to the largest
level, and taken down on every exit path. With a URL it touches nothing.

Before the first level comes a warm-up (``warm_up``): what the server starts
in the background (the CIM graph loaded into its store, the live grid
simulation) and what its first streamer run does once (read the grid's
measurements, open the remote history) hold its event loop for seconds, so a
level measured over them fails for reasons that are not load.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from rich.table import Table

from . import _ui
from ._docker import ContainerToolMissing, Engine, find_engine
from ._paths import repo_root, server_dir
from ._proc import capture, require_tool, run, uv_server
from .smoke import DEFAULT_URL, http_get, server_logs, teardown, unreachable_hint, wait_for_healthz

CAP_VARIABLE = "PMU_TEST_STREAMER_MAX_RUNS"
DRIVER = "loadtest_pmu_test_streamer.py"
#: What the server starts in the background, each a GET that answers 503 until it is done, in order.
STARTED = (
    ("/api/cim-graph/layout", "the CIM graph is loaded"),
    ("/api/time-window/channels", "the live grid is streaming"),
)
#: How long the warm-up waits for all of ``STARTED``.
STARTUP_WAIT_S = 180.0
#: One GET's timeout: the channel list itself waits up to a minute for the live grid's first frame.
_STARTUP_GET_S = 70.0
#: The services whose CPU and memory the table shows, when compose runs them, and their labels.
SHOWN = {"server": "server", "module-worker": "worker"}


@dataclass(frozen=True)
class Thresholds:
    """What every level must meet. Per client unless it says otherwise."""

    frame_share: float = 0.95  # distinct frames per second, of the source's rate × speed
    progress: float = 0.95  # stream time per wall second, of the speed
    stall_share: float = 0.01  # gaps between frames over three intervals, of all gaps
    stats_share: float = 0.95  # state messages with frame stats about their frame
    command_s: float = 2.0  # switch, play and seek, slowest client
    summary_s: float = 5.0  # a range summary's answer, slowest client
    healthz_p99_ms: float = 100.0  # the server's event loop, during the level


def parse_clients(text: str) -> list[int]:
    """``"2,4,8"`` → ``[2, 4, 8]``: positive, each once, in the order given."""
    levels: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) < 1:
            raise ValueError(f"--clients takes positive whole numbers separated by commas, not {text!r}")
        if int(part) not in levels:
            levels.append(int(part))
    if not levels:
        raise ValueError("--clients needs at least one level")
    return levels


def evaluate(summary: dict, limits: Thresholds = Thresholds()) -> list[tuple[str, bool, str]]:
    """``(label, passed, detail)`` per threshold, for one level's driver summary."""
    clients, served = summary["clients"], summary["served"]
    detail = f"{served}/{clients}"
    if summary.get("failures"):
        detail += f"; {summary['failures'][0]}"
    if 1013 in summary.get("close_codes", []):
        detail += f"; at the run cap: raise {CAP_VARIABLE} on the server"
    checks = [("every client is served", served == clients, detail)]
    if served == 0:
        return checks

    def at_least(label: str, value: float | None, floor: float, shown: str) -> None:
        checks.append((label, value is not None and value >= floor, shown if value is not None else "no data"))

    speed = summary.get("speed") or 1.0
    expected = (summary.get("data_rate") or 0.0) * speed
    fps = summary.get("frames_per_s_min")
    at_least(
        f"every frame arrives (≥ {limits.frame_share:.0%} of {expected:g}/s)",
        fps, limits.frame_share * expected, f"slowest client {fps or 0:.2f}/s",
    )
    pace = summary.get("progress_min")
    at_least(
        f"playback keeps time (≥ {limits.progress:.0%} of {speed:g}×)",
        pace, limits.progress * speed, f"slowest client {pace or 0:.3f}×",
    )
    stats = summary.get("stats_share_min")
    at_least(
        f"modules keep up (frame stats on ≥ {limits.stats_share:.0%} of messages)",
        stats, limits.stats_share, f"worst client {stats or 0:.1%}",
    )

    stalls = summary.get("stall_share_max")
    checks.append((
        f"no stalls (≤ {limits.stall_share:.0%} of gaps over three intervals)",
        stalls is not None and stalls <= limits.stall_share,
        "no data" if stalls is None else f"{summary.get('stalls', 0)} stall(s), worst client {stalls:.2%}",
    ))

    commands = [summary.get(k) for k in ("switch_s_max", "play_s_max", "seek_s_max")]
    slowest = None if None in commands else max(commands)
    lost = summary.get("seek_timeouts", 0)
    shown = "no data" if slowest is None else f"slowest {slowest * 1000:.0f} ms"
    checks.append((
        f"switch, play and seek answer within {limits.command_s:g} s",
        slowest is not None and slowest <= limits.command_s and not lost,
        shown + (f"; {lost} seek(s) never landed" if lost else ""),
    ))

    answer = summary.get("summary_s_max")
    late = summary.get("summary_timeouts", 0)
    shown = "no data" if answer is None else f"slowest {answer * 1000:.0f} ms"
    checks.append((
        f"a range summary answers within {limits.summary_s:g} s",
        answer is not None and answer <= limits.summary_s and not late,
        shown + (f"; {late} never answered" if late else ""),
    ))

    health = summary.get("healthz_ms_p99")
    failed = summary.get("healthz_failed", 0)
    shown = "no data" if health is None else f"p99 {health:.1f} ms"
    checks.append((
        f"the server stays responsive (/healthz p99 ≤ {limits.healthz_p99_ms:g} ms)",
        health is not None and health <= limits.healthz_p99_ms and not failed,
        shown + (f"; {failed} failed" if failed else ""),
    ))

    unexpected = summary.get("unexpected_notices") or {}
    shown = "; ".join(f"{count}× {text}" for text, count in unexpected.items())
    checks.append(("nothing unexpected on the error tray", not unexpected, shown[:300]))
    return checks


# --- container stats -----------------------------------------------------------------

_SIZE = re.compile(r"^\s*([\d.]+)\s*([KMGT]?i?B)\s*$")
#: Docker reports binary units (MiB), podman decimal ones (MB).
_UNITS = {
    "B": 1 / 2**20, "KiB": 1 / 2**10, "MiB": 1.0, "GiB": 2**10, "TiB": 2**20,
    "kB": 1e3 / 2**20, "KB": 1e3 / 2**20, "MB": 1e6 / 2**20, "GB": 1e9 / 2**20, "TB": 1e12 / 2**20,
}


def mebibytes(text: str) -> float | None:
    """``"216.9MiB"`` → 216.9; ``None`` when unreadable."""
    match = _SIZE.match(text)
    if not match or match.group(2) not in _UNITS:
        return None
    return float(match.group(1)) * _UNITS[match.group(2)]


def parse_stats_line(line: str) -> tuple[str, float, float | None] | None:
    """One ``<name>\\t<cpu %>\\t<used / limit>`` line → ``(name, cpu %, MiB used)``."""
    parts = line.strip().split("\t")
    if len(parts) != 3:
        return None
    try:
        cpu = float(parts[1].strip().rstrip("%"))
    except ValueError:
        return None
    return parts[0].strip(), cpu, mebibytes(parts[2].split("/")[0])


class StatsSampler:
    """``<engine> stats --no-stream`` over the compose project's running containers,
    in a thread, until stopped. Best effort: with no compose containers, or an
    engine whose stats cannot be read, it records nothing and says so once."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.rows: list[tuple[datetime, str, float, float | None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.services = self._services()

    def _services(self) -> dict[str, str]:
        try:
            listed = capture(self.engine.compose_cmd("ps", "--format", "{{.Name}}\t{{.Service}}"), cwd=repo_root(), timeout=30)
        except Exception:  # noqa: BLE001 -- no figures, not a failed load test
            return {}
        if listed.returncode != 0:
            return {}
        pairs = (line.split("\t") for line in listed.stdout.splitlines() if line.count("\t") == 1)
        return {name.strip(): service.strip() for name, service in pairs}

    def start(self) -> bool:
        if not self.services:
            return False
        self._thread = threading.Thread(target=self._loop, name="load-stats", daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        argv = [self.engine.cli, "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}", *self.services]
        while not self._stop.is_set():
            try:
                sampled = capture(argv, cwd=repo_root(), timeout=30)
            except Exception:  # noqa: BLE001 -- a missed sample is not a failure
                sampled = None
            now = datetime.now(timezone.utc)
            for line in sampled.stdout.splitlines() if sampled else []:
                parsed = parse_stats_line(line)
                if parsed and parsed[0] in self.services:
                    self.rows.append((now, self.services[parsed[0]], parsed[1], parsed[2]))
            self._stop.wait(0.5 if sampled else 5.0)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=35)

    def window(self, start: datetime, end: datetime) -> dict[str, dict[str, float | None]]:
        """Per service: mean CPU % (of one core) and the last memory reading in [start, end]."""
        out: dict[str, dict[str, float | None]] = {}
        for service in sorted(set(self.services.values())):
            rows = [r for r in self.rows if r[1] == service and start <= r[0] <= end]
            if rows:
                out[service] = {"cpu": sum(r[2] for r in rows) / len(rows), "mem_mib": rows[-1][3]}
        return out


# --- the report ----------------------------------------------------------------------

def _ms(seconds: float | None) -> str:
    return "–" if seconds is None else f"{seconds * 1000:.0f}"


def _num(value: float | None, form: str) -> str:
    return "–" if value is None else format(value, form)


def metrics(level: dict) -> list[tuple[str, str]]:
    """One level as ``(metric, value)`` rows: the table's column for it."""
    s = level["summary"]
    rows = [
        ("Served", f"{s['served']}/{s['clients']}"),
        ("Frames/s min", _num(s.get("frames_per_s_min"), ".1f")),
        ("Pace min", _num(s.get("progress_min"), ".2f") + "×"),
        ("Stalls", str(s.get("stalls", 0))),
        ("Stats min", _num(s.get("stats_share_min"), ".1%")),
        ("Switch ms p50/max", f"{_ms(s.get('switch_s_p50'))}/{_ms(s.get('switch_s_max'))}"),
        ("Seek ms max", _ms(s.get("seek_s_max"))),
        ("Summary ms max", _ms(s.get("summary_s_max"))),
        ("/healthz ms p99", _num(s.get("healthz_ms_p99"), ".1f")),
    ]
    for service, label in SHOWN.items():
        seen = level["containers"].get(service)
        rows.append((f"{label} CPU %", "–" if not seen else f"{seen['cpu']:.0f}"))
        rows.append((f"{label} MiB", "–" if not seen or seen["mem_mib"] is None else f"{seen['mem_mib']:.0f}"))
    return rows


def grid(levels: list[dict]) -> tuple[list[str], list[list[str]]]:
    """Headers (``Clients``, then each level's count) and one row per metric."""
    columns = [metrics(level) for level in levels]
    names = [name for name, _ in columns[0]] if columns else []
    rows = [[name, *(column[i][1] for column in columns)] for i, name in enumerate(names)]
    return ["Clients", *(str(level["summary"]["clients"]) for level in levels)], rows


def print_table(levels: list[dict]) -> None:
    head, rows = grid(levels)
    table = Table()
    for i, title in enumerate(head):
        table.add_column(title, justify="left" if i == 0 else "right", no_wrap=True)
    for cells in rows:
        table.add_row(*cells)
    _ui.console.print(table)
    _ui.info("Min/max: the worst client. Pace: stream time per wall second.")
    _ui.info("Stalls: gaps over 3 frame intervals. Stats: messages with frame stats.")
    _ui.info("CPU: % of one core, steady-window mean. MiB: the last reading.")


def markdown(levels: list[dict], failures: list[str], warm_notes: tuple[str, ...] | list[str] = ()) -> str:
    head, rows = grid(levels)
    lines = ["## PMU test streamer load test", "", "| " + " | ".join(head) + " |", "|---" + "|--:" * (len(head) - 1) + "|"]
    lines += ["| " + " | ".join(cells) + " |" for cells in rows]
    if failures:
        lines += ["", "**Over a threshold:**", *(f"- {f}" for f in failures)]
    else:
        lines += ["", "Every level within its thresholds."]
    if warm_notes:
        lines += ["", "**Warm-up (the first level may include the server's start-up):**", *(f"- {n}" for n in warm_notes)]
    return "\n".join(lines) + "\n"


# --- the run -------------------------------------------------------------------------


def _is_compose_url(base: str) -> bool:
    """Whether ``base`` is where this repo's compose stack serves (port 8000 here),
    so its containers are the server under test."""
    return re.fullmatch(r"https?://(127\.0\.0\.1|localhost):8000", base) is not None


def _engine_if_any() -> Engine | None:
    try:
        return find_engine()
    except ContainerToolMissing:
        return None


def _reason(body: str) -> str:
    """A FastAPI error's ``detail``, else the body's start."""
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        detail = None
    return str(detail) if detail else body.strip()[:120]


def wait_until_started(base: str, budget: float = STARTUP_WAIT_S) -> list[str]:
    """Wait, at most ``budget`` seconds in all, for each of ``STARTED`` to answer 2xx. What
    was not waited for, and why, as notes: an app the server does not serve (404) is
    skipped, and a grid that cannot be had (503 "not available") ends the wait, since the
    live grid then never starts."""
    deadline = time.monotonic() + budget
    notes: list[str] = []
    for path, what in STARTED:
        waited = False
        while True:
            try:
                status, body = http_get(base + path, timeout=_STARTUP_GET_S)
            except OSError as error:
                status, body = 0, str(error)
            if 200 <= status < 300:
                if waited:
                    _ui.console.print()
                _ui.info(f"Started: {what}.")
                break
            reason = _reason(body)
            if status == 404:
                notes.append(f"{path} is not served (404): not waited for")
                break
            if status == 503 and "not available" in reason:
                notes.append(f"{path}: {reason}; the live grid will not start, so not waited for")
                return notes
            if time.monotonic() >= deadline:
                if waited:
                    _ui.console.print()
                notes.append(f"not started after {budget:.0f} s: {what} ({path}: {status or 'no answer'}, {reason})")
                return notes
            _ui.console.print(".", end="")
            waited = True
            time.sleep(1)
    return notes


def warm_up(base: str, seconds: float, speed: float, source: str) -> list[str]:
    """Wait for the server to finish starting, then play one client for ``seconds``,
    unjudged. Notes on what could not be warmed up; the levels run regardless."""
    _ui.section(f"Warm-up: the server's start, then 1 client for {seconds:g} s (not judged)")
    notes = wait_until_started(base)
    driver = server_dir() / "tools" / DRIVER
    with tempfile.TemporaryDirectory() as folder:
        options = ["--clients", "1", "--steady", str(seconds), "--speed", str(speed), "--source", source]
        code = run(uv_server("python", str(driver), base, *options, "--out", str(Path(folder) / "warm-up.json")), cwd=repo_root())
    if code != 0:
        notes.append(f"the warm-up client failed (exit code {code})")
    for note in notes:
        _ui.info(f"Note: {note}; the first level may include the server's start-up.")
    return notes


def load(
    url: str | None,
    clients: list[int],
    steady: float,
    speed: float,
    source: str,
    json_path: Path | None,
    limits: Thresholds = Thresholds(),
    warmup: float = 15.0,
) -> int:
    """Run every level, after ``warm_up`` unless ``warmup`` is 0; the exit code."""
    require_tool("uv", purpose="for the load test's WebSocket clients")
    base = (url or DEFAULT_URL).rstrip("/")
    report = _ui.Report()
    engine: Engine | None = None
    started = False
    sampler: StatsSampler | None = None
    levels: list[dict] = []
    warm_notes: list[str] = []

    _ui.section("Server under test")
    try:
        if url:
            _ui.info(f"Using the server at {base} (not managing its lifecycle)")
            engine = _engine_if_any()
        else:
            engine = find_engine()
            cap = max(max(clients), 8)
            _ui.info(f"Container engine: {engine.name} ({engine.cli}); compose: {' '.join(engine.compose)}")
            _ui.info("Clearing any running p-swamp containers…")
            teardown(engine)
            _ui.info(f"Starting the compose stack from scratch (builds the image), {CAP_VARIABLE}={cap}…")
            started = True
            code = run(
                engine.compose_cmd("up", "-d", "--build", "--force-recreate", "--wait"),
                cwd=repo_root(),
                env={CAP_VARIABLE: str(cap)},
            )
            if code != 0:
                _ui.error("the stack did not come up (`compose up` failed)")
                server_logs(engine)
                return 1
        if not wait_for_healthz(base):
            _ui.error(unreachable_hint(base, engine))
            return 1
        if warmup > 0:
            warm_notes = warm_up(base, warmup, speed, source)
        if engine is not None and _is_compose_url(base):
            sampler = StatsSampler(engine)
            if "server" not in sampler.services.values() or not sampler.start():
                sampler = None
        if sampler is None:
            _ui.info("The server under test is not this repo's compose stack: no CPU or memory figures.")

        driver = server_dir() / "tools" / DRIVER
        for count in clients:
            _ui.section(f"{count} client(s), {steady:g} s steady at {speed:g}× on {source!r}")
            with tempfile.TemporaryDirectory() as folder:
                out = Path(folder) / "level.json"
                options = ["--clients", str(count), "--steady", str(steady), "--speed", str(speed), "--source", source]
                argv = uv_server("python", str(driver), base, *options, "--out", str(out))
                code = run(argv, cwd=repo_root())
                if code != 0 or not out.exists():
                    report.record(f"{count} clients: the driver ran", False, f"exit code {code}")
                    continue
                result = json.loads(out.read_text(encoding="utf-8"))
            summary = result["summary"]
            start, end = (datetime.fromisoformat(t) for t in summary["steady_utc"])
            level = {"summary": summary, "containers": sampler.window(start, end) if sampler else {}, "checks": []}
            for label, passed, detail in evaluate(summary, limits):
                report.record(f"{count} clients: {label}", passed, detail)
                level["checks"].append({"check": label, "passed": passed, "detail": detail})
            if (summary.get("driver_lag_ms_p99") or 0) > 50:
                lag = summary["driver_lag_ms_p99"]
                _ui.info(f"Note: the driver itself lagged (p99 {lag:.0f} ms); its numbers may understate the server.")
            level["clients"] = result["clients"]
            levels.append(level)

        _ui.section("Results")
        if levels:
            print_table(levels)
        if json_path is not None:
            json_path.write_text(
                json.dumps(
                    {"thresholds": asdict(limits), "warmup": {"seconds": warmup, "notes": warm_notes}, "levels": levels},
                    indent=1,
                    default=str,
                ),
                encoding="utf-8",
            )
            _ui.info(f"Every number: {json_path}")
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as out:
                out.write(markdown(levels, report.failures, warm_notes))
        if report.failures and started and engine is not None:
            server_logs(engine)
        return report.finish(
            "Load test passed: every level within its thresholds.",
            "`--json PATH` keeps every client's numbers; `uv run pswamp test load --help` lists the thresholds.",
        )
    finally:
        if sampler is not None:
            sampler.stop()
        if started and engine is not None:
            _ui.console.print("\nStopping the stack…")
            run(engine.compose_cmd("down", "--remove-orphans"), cwd=repo_root(), quiet=True)
