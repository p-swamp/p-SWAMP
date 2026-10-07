"""``pswamp test``: the test suites (were the run-*-tests.sh and e2e-smoke-test.sh scripts)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Optional

import typer

from .. import _ui, smoke as smoke_test
from .._docker import find_engine
from .._paths import desktop_dir, e2e_dir, repo_root, server_dir
from .._proc import require_tools, run

app = typer.Typer(
    help=(
        "Run a test suite. `server` is the fast hermetic one (and what CI gates on); "
        "`smoke` and `playwright` start the real container; `desktop` needs external infrastructure."
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
