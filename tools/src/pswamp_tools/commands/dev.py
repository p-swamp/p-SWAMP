"""``pswamp dev``: the local dev loop, a hot-reloaded server and web client
(were the two start-local-hotloaded-*.sh scripts)."""

from __future__ import annotations

import threading
import typer

from .. import _net, _ui
from .._docker import Engine, find_engine
from .._paths import client_dir, repo_root
from .._proc import capture, require_tool, run, run_filtered

app = typer.Typer(
    help=(
        "The local dev loop: `dev server` (the containerised server, hot-reloaded) in one "
        "terminal, then `dev client` (Vite with HMR) in another. Neither regenerates the api "
        "contract: run `uv run pswamp api generate` after an api change."
    ),
    no_args_is_help=True,
)

# Compose probes /healthz every 10s; those lines are noise in the log view.
HEALTHZ_LINE = "GET /healthz HTTP/1.1"
VITE_URL = "http://localhost:5173/"


def supports_watch(engine: Engine) -> bool:
    """Whether this compose has ``up --watch`` (docker compose >= 2.22 does; podman-compose does not)."""
    result = capture(engine.compose_cmd("up", "--help"), cwd=repo_root(), timeout=60)
    return "--watch" in (result.stdout or "") + (result.stderr or "")


def server_command(engine: Engine, watch: bool) -> list[str]:
    # --build is not optional: compose builds only when the image is missing, and
    # watch syncs only edits made while it runs, so a change made while the stack
    # was down (a new, renamed or deleted module) would run from a stale image.
    return engine.compose_cmd("up", "--watch", "--build") if watch else engine.compose_cmd("up", "--build")


@app.command()
def server() -> None:
    """Start the state server on 127.0.0.1:8000: `compose up --watch --build`, logs in this terminal.

    The FastAPI/uvicorn server runs in its container with hot reload (compose
    syncs the server, models/, core/, modules/ and desktop/src/ in, and uvicorn --reload picks
    the edit up), next to Kafka and the module workers. This terminal is the
    local log view (the /healthz probe lines are filtered out), and Ctrl-C STOPS
    the stack rather than leaving it bound to port 8000.

    The image is always rebuilt (`--build`; a warm no-op rebuild takes seconds),
    because compose watch never sees edits made while the stack was down.

    Works with docker or podman. A compose without `up --watch` (podman-compose)
    falls back to `up --build`: the server then runs without hot reload, so
    restart it after an edit.

    NOT hot-reloaded: the api contract (`uv run pswamp api generate`).
    """
    engine = find_engine()
    _ui.info(f"Container engine: {engine.name}; compose: {' '.join(engine.compose)}")
    watch = supports_watch(engine)
    if not watch:
        _ui.console.print(
            f"[yellow]note:[/yellow] `{' '.join(engine.compose)} up` has no --watch here, so hot reload is "
            "unavailable: starting with `up --build`. Restart this command after an edit, or install the "
            "Docker Compose v2 plugin (podman compose uses it when present)."
        )
    raise typer.Exit(run_filtered(server_command(engine, watch), drop=HEALTHZ_LINE, cwd=repo_root()))


@app.command()
def client(
    no_browser: bool = typer.Option(
        False, "--no-browser", envvar="NO_BROWSER", help="Don't open the browser once Vite is up."
    ),
) -> None:
    """Start the Vite/React web client with HMR on http://localhost:5173 and open it.

    Vite proxies /api to the server on :8000 (vite.config.ts), so run
    `uv run pswamp dev server` in another terminal first: same-origin, just as
    in the image, where the server serves the production build at / instead.
    Installs the web client's dependencies (`npm ci`) on a fresh checkout.

    HMR does NOT cover the generated api types (src/api/schema.ts): Vite strips
    types rather than checking them, so a client built against a stale contract
    looks fine here and fails in `uv run pswamp check`.
    """
    require_tool("npm", purpose="for the web client")
    web = client_dir()
    if not (web / "node_modules").is_dir():
        _ui.info("Installing web client dependencies (first run)…")
        if run(["npm", "ci"], cwd=web) != 0:
            raise typer.Exit(1)

    if not no_browser:
        threading.Thread(target=_open_when_up, args=(VITE_URL,), daemon=True).start()

    # The api doc is served by the server, not Vite: the dev proxy forwards only
    # /api, so /docs on :5173 falls through to the SPA.
    _ui.console.print()
    _ui.console.print("API docs:      http://localhost:8000/docs  (ReDoc at /redoc, raw document at /openapi.json)")
    _ui.console.print("               served by `uv run pswamp dev server`, not by Vite on :5173")
    _ui.console.print()
    raise typer.Exit(run(["npm", "run", "dev"], cwd=web))


def _open_when_up(url: str) -> None:
    # 60 attempts, 0.5s apart: Vite gets 30s.
    if _net.wait_until_answers(url, 60, dots=False):
        _net.open_browser(url)
    else:
        _ui.info(f"Vite did not come up within 30s; open {url} manually.")
