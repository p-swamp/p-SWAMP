"""The end-to-end smoke test: a real server, its HTTP surface, and two flows over the wire.

The port of scripts/e2e-smoke-test.sh. Without a URL it owns the server: every
p-swamp container is removed first (a reused one is not the tree under test:
``restart: unless-stopped`` keeps old ones up, compose ``watch`` never syncs a
delete, and the web client is baked in at build time), the compose stack is
built and started from scratch, and it is taken down again on every exit path.
With a URL it touches nothing: the caller owns that server (the CI path).

Checks, in order:

1. ``/healthz`` answers — the process is serving
2. ``/`` serves the built web client — the client is baked into the image
3. a deep link serves the shell — SPAStaticFiles' history fallback
4. a missing asset still 404s — that fallback isn't swallowing everything
5. ``/openapi.json`` has the commands — the api describes itself
6. the counter flow — app/server-python/tools/smoketest_reference_subapp.py
7. the PMU test streamer — app/server-python/tools/smoketest_pmu_test_streamer.py

6 and 7 run in the server's environment (``websockets`` comes with
``uvicorn[standard]``). Every check runs even if one fails, except that nothing
runs against a server that never answered ``/healthz``.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

from . import _ui
from ._docker import Engine, find_engine
from ._paths import repo_root, server_dir
from ._proc import capture, require_tool, run, uv_server

DEFAULT_URL = "http://127.0.0.1:8000"
HEALTHZ_ATTEMPTS = 30
IMAGE = "p-swamp:latest"


def http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """``(status, body)`` for a GET; an HTTP error status is a result, not an exception.

    A connection failure (refused, reset, timed out) raises ``OSError``.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def _body(url: str) -> str | None:
    """The body of a 2xx response, else None (any failure)."""
    try:
        status, body = http_get(url)
    except OSError:
        return None
    return body if 200 <= status < 300 else None


def wait_for_healthz(base: str, attempts: int = HEALTHZ_ATTEMPTS) -> bool:
    """Poll ``/healthz`` once a second; a dot per attempt so a slow start is visibly not a hang."""
    for attempt in range(1, attempts + 1):
        if _body(f"{base}/healthz") is not None:
            if attempt > 1:
                _ui.console.print()
            return True
        _ui.console.print(".", end="")
        time.sleep(1)
    _ui.console.print()
    return False


def http_checks(base: str, report: _ui.Report) -> None:
    def built_client() -> bool:
        # id="root" is the mount point; an assets/ reference proves this is the
        # BUILT client, not the dev shell (which points at /src/main.tsx).
        body = _body(f"{base}/")
        return body is not None and 'id="root"' in body and "/assets/" in body

    def deep_link() -> bool:
        body = _body(f"{base}/reference-subapp")
        return body is not None and 'id="root"' in body

    def missing_asset_404() -> bool:
        try:
            return http_get(f"{base}/assets/does-not-exist.js")[0] == 404
        except OSError:
            return False

    def openapi() -> bool:
        body = _body(f"{base}/openapi.json")
        return body is not None and "reference_subapp_bump" in body

    report.step("GET / serves the built web client", built_client)
    report.step("GET /reference-subapp serves the shell (deep link)", deep_link)
    report.step("GET /assets/does-not-exist.js still 404s", missing_asset_404)
    report.step("GET /openapi.json describes the Reference example's commands", openapi)


def flows(base: str, report: _ui.Report) -> None:
    tools = server_dir() / "tools"
    _ui.section("Reference example (commands up, state down)")
    report.step(
        "counter flow",
        lambda: run(uv_server("python", str(tools / "smoketest_reference_subapp.py"), base), cwd=repo_root()),
    )
    _ui.section("PMU test streamer (the server data architecture)")
    report.step(
        "streamer flow",
        lambda: run(uv_server("python", str(tools / "smoketest_pmu_test_streamer.py"), base), cwd=repo_root()),
    )


def teardown(engine: Engine) -> None:
    """Remove the compose stack and any other container running the p-swamp image."""
    root = repo_root()
    run(engine.compose_cmd("down", "--remove-orphans", "-t", "5"), cwd=root, quiet=True)
    listed = capture([engine.cli, "ps", "-aq", "--filter", f"ancestor={IMAGE}"], cwd=root)
    ids = listed.stdout.split() if listed.returncode == 0 else []
    removed = [cid for cid in ids if capture([engine.cli, "rm", "-f", cid], cwd=root).returncode == 0]
    if removed:
        _ui.info(f"Removed stray p-swamp container(s): {' '.join(removed)}")


def server_logs(engine: Engine) -> None:
    _ui.console.print("\nLast 50 lines of server log:")
    run(engine.compose_cmd("logs", "--tail", "50", "server"), cwd=repo_root())


def unreachable_hint(base: str, engine: Engine | None) -> str:
    hint = f"the server did not answer on {base}/healthz after {HEALTHZ_ATTEMPTS}s."
    if engine is not None and engine.is_podman:
        hint += (
            "\n  The container may be healthy but unreachable from the host: with podman on Windows/macOS, "
            "host port forwarding (8000 -> the podman machine) is a known failure point. Check "
            "`podman ps` (is 0.0.0.0:8000->8000 listed?), `podman machine inspect` and "
            "`curl http://127.0.0.1:8000/healthz`; restarting the machine (`podman machine stop; podman machine start`) "
            "often restores forwarding."
        )
    elif engine is not None:
        hint += " Check `docker compose ps` and `docker compose logs server`."
    else:
        hint += " Is the server running at that URL?"
    return hint


def smoke(url: str | None) -> int:
    """Run the smoke test; the exit code."""
    require_tool("uv", purpose="for the smoke test's WebSocket clients")
    base = (url or DEFAULT_URL).rstrip("/")
    report = _ui.Report()
    engine: Engine | None = None
    started = False

    _ui.section("Server under test")
    try:
        if url:
            _ui.info(f"Using the server at {base} (not managing its lifecycle)")
        else:
            engine = find_engine()  # ContainerToolMissing is reported by main, before anything starts
            _ui.info(f"Container engine: {engine.name} ({engine.cli}); compose: {' '.join(engine.compose)}")
            _ui.info("Clearing any running p-swamp containers…")
            teardown(engine)
            _ui.info("Starting the compose server from scratch (builds the image)…")
            # --wait blocks until the compose healthcheck passes; --build and
            # --force-recreate because compose otherwise reuses a stale image or container.
            started = True
            code = run(engine.compose_cmd("up", "-d", "--build", "--force-recreate", "--wait"), cwd=repo_root())
            if code != 0:
                _ui.error("the server did not come up (`compose up` failed)")
                server_logs(engine)
                return 1
            _ui.info(f"Server up at {base}")

        _ui.section("HTTP surface")
        if not report.record("GET /healthz answers", wait_for_healthz(base)):
            _ui.error(unreachable_hint(base, engine))
            _ui.info("Skipping the remaining checks: there is no server to check.")
        else:
            http_checks(base, report)
            flows(base, report)

        if report.failures and started and engine is not None:
            server_logs(engine)
        return report.finish("Smoke test passed — the rig works end to end.")
    finally:
        if started and engine is not None:
            _ui.console.print("\nStopping the server…")
            run(engine.compose_cmd("down", "--remove-orphans"), cwd=repo_root(), quiet=True)
