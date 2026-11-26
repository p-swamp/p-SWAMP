"""``pswamp test``: the test suites (were the run-*-tests.sh and e2e-smoke-test.sh scripts)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Optional

import typer

from .. import _ui, load as load_test, smoke as smoke_test
from .._docker import find_engine
from .._paths import desktop_dir, e2e_dir, repo_root, server_dir
from .._proc import require_tools, run

app = typer.Typer(
    help=(
        "Run a test suite. `server` is the fast hermetic one (and what CI gates on); "
        "`smoke`, `playwright` and `load` start the real container; `desktop` needs external infrastructure."
    ),
    no_args_is_help=True,
)

# Unknown options and extra arguments are collected rather than rejected, so
# `pswamp test server -k lock -v` and `pswamp test server -- -k lock -v` both
# hand `-k lock -v` to pytest.
PASS_THROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


@app.command(context_settings=PASS_THROUGH)
def server(ctx: typer.Context) -> None:
    """The server, models, core, modules and tools unit tests: fast, hermetic, nothing binds a port.

    Runs pytest from app/server-python with its config (`-c pyproject.toml`),
    whose `testpaths` names app/server-python/tests, models/tests, core/tests,
    each module project's tests/ under modules/, and tools/tests; a new test_*.py there is picked
    up with no change here. None of those folders is a package, so a test file
    name must be unique across all of them. One module's tests alone:
    `pswamp test module <name>`.

    Every extra argument goes to pytest verbatim:

      pswamp test server -v

      pswamp test server -- -k lock -x

      pswamp test server tests/test_hub_registry.py::test_new_client_refused_when_all_slots_in_use
    """
    require_tools("uv", purpose="for the server test environment")
    # `-c pyproject.toml` pins the config: otherwise pytest picks it from the
    # common ancestor of the paths it is given and loses pythonpath/asyncio_mode.
    raise typer.Exit(run(["uv", "run", "pytest", "-c", "pyproject.toml", *ctx.args], cwd=server_dir()))


def find_module_project(name: str, root: Path) -> Path | None:
    """The module project ``name`` names: its folder under modules/ (``frame-stats``),
    its entry-point name or its package name (``frame_stats``); ``None`` if none does."""
    wanted = name.strip().strip("/\\").removeprefix("modules/").lower()
    for manifest in sorted((root / "modules").glob("*/pyproject.toml")):
        project = manifest.parent
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        names = {project.name, project.name.replace("-", "_")}
        names |= set(data.get("project", {}).get("entry-points", {}).get("pswamp.modules", {}))
        if wanted in {n.lower() for n in names}:
            return project
    return None


@app.command(context_settings=PASS_THROUGH)
def module(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="The module: its folder under modules/ or its entry-point name (frame-stats)."),
) -> None:
    """One module's tests (modules/<name>/tests/), with the server's pytest config.

    The same tests `pswamp test server` runs, narrowed to one module project.
    Extra arguments go to pytest verbatim:

      pswamp test module frame-stats

      pswamp test module range-summary -- -k plain -v
    """
    require_tools("uv", purpose="for the server test environment")
    root = repo_root()
    project = find_module_project(name, root)
    if project is None:
        known = ", ".join(sorted(p.parent.name for p in (root / "modules").glob("*/pyproject.toml")))
        _ui.error(f"no module project named {name!r} under modules/ (there are: {known})")
        raise typer.Exit(2)
    tests = os.path.relpath(project / "tests", server_dir())
    raise typer.Exit(run(["uv", "run", "pytest", "-c", "pyproject.toml", tests, *ctx.args], cwd=server_dir()))


@app.command(context_settings=PASS_THROUGH)
def desktop(ctx: typer.Context) -> None:
    """The desktop p-swamp package's tests (desktop/tests/), with its `full` extra.

    NOT hermetic: most of them need the `full` extra (PySide6, kafka-python,
    nqkafka, tops-rt, …) and external infrastructure — a Kafka broker, an
    NQKafka/MQTT broker, a Qt display — and have no skip guards, so on a bare
    machine expect errors. A cold run builds that env first (git
    dependencies). Runs from desktop/ against desktop/uv.lock, not the
    workspace's. Extra arguments go to pytest (paths relative to desktop/):

      pswamp test desktop -k geo

      pswamp test desktop -- tests/monitoring -v
    """
    require_tools("uv", purpose="for the desktop test environment")
    _ui.section("Desktop core tests (desktop/tests/)")
    _ui.info("Needs the [full] extra + external infra (Kafka/NQKafka/MQTT brokers, a Qt display).")
    _ui.info("A cold run builds the [full] env first (git deps: synchrophasor, nqkafka, tops-rt).")
    # tests/ explicitly: the desktop project sets no testpaths, so pytest would collect examples/ too.
    raise typer.Exit(run(["uv", "run", "--extra", "full", "pytest", "tests/", *ctx.args], cwd=desktop_dir()))


@app.command()
def playwright(
    url: Optional[str] = typer.Option(
        None,
        "--url",
        envvar="E2E_BASE_URL",
        help="Run against a server already up at this URL and start nothing (sets E2E_BASE_URL).",
    ),
) -> None:
    """The Playwright browser tests (e2e/*.spec.ts) against the real container.

    Without --url, Playwright itself starts the stack with `docker compose up
    --build` (e2e/playwright.config.ts) and takes it down afterwards, so a
    `docker` CLI with compose is required; with only podman, start the server
    yourself and pass --url. Installs e2e/ dependencies on a fresh checkout and
    the chromium browser (idempotent) before running.
    """
    require_tools("npm", "npx", purpose="for the Playwright tests")
    env: dict[str, str] = {}
    if url:
        env["E2E_BASE_URL"] = url
    else:
        engine = find_engine()
        # Playwright runs the literal `docker compose`, so that exact command must work
        # (it does for podman installed as `docker`, too).
        if engine.compose != (engine.cli, "compose") or Path(engine.cli).stem.lower() != "docker":
            _ui.error(
                f"e2e/playwright.config.ts starts the stack with `docker compose`, but the engine here is "
                f"{engine.name} ({' '.join(engine.compose)}).\n"
                "  -> start the server yourself (e.g. `podman compose up -d --build`) and run "
                "`uv run pswamp test playwright --url http://127.0.0.1:8000`"
            )
            raise typer.Exit(1)
    cwd = e2e_dir()
    if not (cwd / "node_modules").is_dir():
        _ui.info("Installing Playwright dependencies (first run)…")
        if run(["npm", "ci"], cwd=cwd) != 0:
            raise typer.Exit(1)
    # Browsers are cached outside node_modules, so a fresh machine needs this
    # even with node_modules present. Idempotent.
    if run(["npx", "playwright", "install", "--with-deps", "chromium"], cwd=cwd) != 0:
        raise typer.Exit(1)
    raise typer.Exit(run(["npx", "playwright", "test"], cwd=cwd, env=env))


@app.command()
def smoke(
    url: Optional[str] = typer.Option(
        None,
        "--url",
        envvar="SMOKETEST_URL",
        help="Test a server already running at this URL and manage no lifecycle (the CI path).",
    ),
) -> None:
    """The end-to-end smoke test: build and start the container, check it over the wire, stop it.

    Without --url it ALWAYS starts from scratch: every p-swamp container is
    removed, the image rebuilt and the compose stack recreated (a reused server
    is not the tree under test), then taken down on exit. Works with docker or
    podman (including podman installed as `docker`).

    Checks: /healthz; / serves the built client; a deep link serves the SPA
    shell; a missing asset still 404s; /openapi.json lists the commands; the
    Reference example's counter flow (POST commands up, state down the socket);
    the PMU test streamer flow. It tests the wire, not the UI (that is
    `pswamp test playwright`). Exits non-zero if any check failed.
    """
    _ = repo_root()  # fail early, before touching any container, if not in the repo
    raise typer.Exit(smoke_test.smoke(url))


@app.command()
def load(
    url: Optional[str] = typer.Option(
        None,
        "--url",
        envvar="LOADTEST_URL",
        help="Test a server already running at this URL and manage no lifecycle (the CI path).",
    ),
    clients: str = typer.Option("2,4,8,16,32", "--clients", help="Concurrent clients, one level each, comma-separated."),
    steady: float = typer.Option(60.0, "--steady", min=5.0, help="Seconds of steady state measured per level."),
    speed: float = typer.Option(1.0, "--speed", min=0.1, max=10.0, help="Replay speed every client plays at."),
    source: str = typer.Option("remote", "--source", help="The streamer source every client plays."),
    json_path: Optional[Path] = typer.Option(None, "--json", help="Write every level's and every client's numbers here."),
    warmup: float = typer.Option(
        15.0, "--warmup", min=0.0, help="Seconds one unjudged client plays before the first level, once the server has started; 0: no warm-up."
    ),
) -> None:
    """The PMU test streamer under load: N concurrent clients, each with its own run.

    Each level opens N clients at once, each with its own client id: the page's
    two sockets, the source pressed (`remote`, the remote history, by
    default), play, and midway a seek and a one-second range summary. After
    the steady window each client pauses and leaves. A level fails when any
    client is refused or misses one of these (thresholds in
    tools/src/pswamp_tools/load.py):

      every frame arrives (>= 95% of the source's rate x speed, per client);
      playback keeps time (>= 95%); no stalls (<= 1% of gaps over three frame
      intervals); frame stats on >= 95% of state messages; switch, play and
      seek within 2 s and a summary within 5 s (slowest client); /healthz p99
      <= 100 ms; nothing but outage notices on the error tray.

    First comes a warm-up, which nothing is judged on: it waits (3 min at
    most) until the CIM graph is loaded and the live grid is streaming,
    which the server does in the background after /healthz answers, then one
    client plays for --warmup seconds, so what a server's first run does once
    (reading the grid's measurements) stays out of the first level.

    Without --url it owns the server like `pswamp test smoke`: every p-swamp
    container is removed (a running dev stack included), the compose stack is
    built and started with PMU_TEST_STREAMER_MAX_RUNS raised to the largest
    level, and taken down afterwards. Its server is the dev one (uvicorn
    --reload and its polling watcher). With --url the server's own cap
    applies, and more clients than that are refused (1013). When the server
    under test is this repo's compose stack (:8000 here), the table adds the
    server's and the module worker's CPU and memory.
    Under GitHub Actions the table is also written to the job summary.

      pswamp test load --clients 8,16 --steady 30

      pswamp test load --url http://127.0.0.1:8000 --json load.json
    """
    _ = repo_root()  # fail early, before touching any container, if not in the repo
    try:
        levels = load_test.parse_clients(clients)
    except ValueError as error:
        _ui.error(str(error))
        raise typer.Exit(2) from None
    if 0 < warmup < 5:
        _ui.error(f"--warmup is 0 (none) or at least 5 seconds, as --steady is, not {warmup:g}")
        raise typer.Exit(2)
    raise typer.Exit(load_test.load(url, levels, steady, speed, source, json_path, warmup=warmup))
