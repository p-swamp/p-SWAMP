"""``pswamp dev``: the local dev loop, a hot-reloaded server and web client
(were the two start-local-hotloaded-*.sh scripts)."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

import typer

from .. import _net, _ui
from .._compose_config import ComposeConfigError, repo_compose_files, resolve
from .._docker import Engine, find_engine
from .._extra_modules import ExtraModulesError, read_extra_modules, variable_for, with_extra_modules
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


def server_command(engine: Engine, watch: bool, compose_file: Path | None = None) -> list[str]:
    # --build is not optional: compose builds only when the image is missing, and
    # watch syncs only edits made while it runs, so a change made while the stack
    # was down (a new, renamed or deleted module) would run from a stale image.
    # A compose_file (the configuration resolved with --extra-modules or
    # --compose-file) replaces the repo's files, from the repo root as ever.
    files = ("-f", str(compose_file), "--project-directory", str(repo_root())) if compose_file else ()
    return engine.compose_cmd(*files, "up", *(("--watch",) if watch else ()), "--build")


def extra_modules_config(config: dict, path: Path, pipeline: str) -> dict:
    """``config`` (the stack's resolved compose configuration), changed to run the modules at
    ``path`` in ``pipeline``. Exits with a one-line error when it cannot be."""
    repo = repo_root()
    try:
        projects = read_extra_modules(path, repo)
        context = path.expanduser().resolve()
        config = with_extra_modules(config, context, projects, pipeline)
    except ExtraModulesError as error:
        _ui.error(f"--extra-modules: {error}")
        raise typer.Exit(2) from error
    modules = ", ".join(name for p in projects for name in p.modules)
    _ui.info(
        f"Extra modules: {modules} (from {context}), in pipelines/{pipeline}.toml through "
        f"{variable_for(pipeline)}, hosted by the extra-modules-worker"
    )
    if (context / ".venv").exists() and not (context / ".dockerignore").exists():
        _ui.console.print(
            f"[yellow]note:[/yellow] {context} has a .venv and no .dockerignore: every build sends the .venv to "
            "the builder. Add a .dockerignore listing .venv/."
        )
    return config


@app.command()
def server(
    extra_modules: Path | None = typer.Option(
        None,
        "--extra-modules",
        metavar="PATH",
        help=(
            "Also run the modules of a project outside this repo (a folder with a pyproject.toml declaring "
            '\\[project.entry-points."pswamp.modules"], or a folder of such projects): installed into the image, '
            "added to the pipeline, hosted by a worker of their own, restarted on an edit of their src/."
        ),
    ),
    pipeline: str = typer.Option(
        "grid-monitor", "--pipeline", help="The pipeline (pipelines/<name>.toml) the extra modules join."
    ),
    compose_files: list[Path] = typer.Option(
        [],
        "--compose-file",
        "-f",
        metavar="PATH",
        help=(
            "A compose file to add after the repo's own (docker-compose.override.yml included), e.g. an override "
            "kept in another project. Unlike `docker compose -f`, its relative paths are relative to its own "
            "folder. Repeatable."
        ),
    ),
) -> None:
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

    With --extra-modules PATH, a module developed outside this repo runs too, in
    the grid monitor's pipeline unless --pipeline says otherwise: see "Trying a
    module from outside the repo" in doc/module-cookbook.md. It needs a compose
    that knows build contexts (Docker Compose v2).

    With --compose-file PATH, the stack is configured by that file too, after the
    repo's own: the grid to load, say, kept in the project you run this from
    (`uv run --project ../p-swamp pswamp dev server -f compose.override.yml`).
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
    repo = repo_root()
    if extra_modules is not None and not (repo / "pipelines" / f"{pipeline}.toml").is_file():
        _ui.error(f"--pipeline {pipeline}: there is no pipelines/{pipeline}.toml")
        raise typer.Exit(2)
    if extra_modules is None and not compose_files:
        raise typer.Exit(run_filtered(server_command(engine, watch), drop=HEALTHZ_LINE, cwd=repo))
    with tempfile.TemporaryDirectory(prefix="pswamp-stack-") as folder:
        try:
            config = resolve(engine, repo, compose_files, Path(folder))
        except ComposeConfigError as error:
            _ui.error(f"compose could not read the configuration:\n{error}")
            raise typer.Exit(1) from error
        if compose_files:
            used = [*repo_compose_files(repo), *(p.expanduser().resolve() for p in compose_files)]
            _ui.info("Compose files: " + ", ".join(str(p) for p in used))
        if extra_modules is not None:
            config = extra_modules_config(config, extra_modules, pipeline)
        compose_file = Path(folder) / "compose.json"
        compose_file.write_text(json.dumps(config, indent=1), encoding="utf-8")
        raise typer.Exit(run_filtered(server_command(engine, watch, compose_file), drop=HEALTHZ_LINE, cwd=repo))


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
