"""``pswamp check``: the static "is the code sound?" gate (was scripts/error_check.sh)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import typer

from .. import _ui, contract
from .._paths import client_dir, repo_root
from .._proc import require_tools, run, uv_server
from .pipelines import pipeline_files, validate_files

# Fully gated: syntax and ruff. `tools` is new with the CLI and starts lint-clean.
LINTED = ("app", "models", "core", "modules", "legacy", "tools")
# Syntax only: the older desktop package ships in the image so it must parse, but
# it has ~334 pyflakes findings to triage before it can join LINTED.
# TODO Add the desktop package (desktop/src) to the ruff check once it is lint-clean.
SYNTAX_ONLY = ("desktop/src",)
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git"}

HELP = """\
Run the static checks: the gate before every push, and what CI runs.

Read-only (never edits a file) and starts nothing. Every check runs even when
one fails; the command exits non-zero if any did.

[bold]Web client[/bold] (app/client-web; `npm ci` first on a fresh checkout)
  - tsc -b ........ type-check
  - eslint . ...... lint

[bold]Python[/bold] (the uv workspace)
  - uv lock --check --offline ... manifests vs the root uv.lock (fix: `uv lock`)
  - syntax ...... every .py under app/, models/, core/, modules/, legacy/, tools/, + desktop/src/ (syntax only)
  - ruff check --select F ... pyflakes (real bugs, not style) over app/, models/, core/, modules/, legacy/, tools/,
    with the ruff pinned in app/server-python's dev group

[bold]Pipelines[/bold]
  - pipelines validate ... every pipelines/*.toml loads: its modules are installed,
    its sources import, and the pipeline is consistent (`pswamp pipelines validate`)

[bold]Api contract[/bold]
  - doc/api/openapi.json and app/client-web/src/api/schema.ts match the code
    (fix: `uv run pswamp api generate`, then commit both). The one check that
    needs the full server environment: a cold run syncs it first.
"""


def python_files(root: Path, folders: tuple[str, ...]) -> Iterator[Path]:
    """Every ``.py`` under ``folders`` (relative to ``root``), skipping caches, venvs and node_modules."""
    for folder in folders:
        base = root / folder
        if not base.is_dir():
            continue
        for directory, subdirs, files in os.walk(base):
            subdirs[:] = sorted(d for d in subdirs if d not in SKIP_DIRS)
            for name in sorted(files):
                if name.endswith(".py"):
                    yield Path(directory) / name


def syntax_errors(files: list[Path], root: Path) -> list[str]:
    """Compile each file in memory (nothing written, unlike py_compile) and describe each failure."""
    errors = []
    for path in files:
        try:
            compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as exc:
            line = getattr(exc, "lineno", None)
            where = path.relative_to(root).as_posix() + (f":{line}" if line else "")
            errors.append(f"{where}: {type(exc).__name__}: {getattr(exc, 'msg', exc)}")
    return errors


def _syntax_step(files: list[Path], root: Path) -> bool:
    errors = syntax_errors(files, root)
    for message in errors:
        _ui.console.print(f"    {message}", markup=False)
    return not errors


def check(
    skip_web: bool = typer.Option(False, "--skip-web", help="Skip tsc and eslint (no Node.js needed for the rest)."),
) -> None:
    root = repo_root()
    needed = ["uv"] if skip_web else ["uv", "node", "npm", "npx"]
    require_tools(*needed, purpose="by pswamp check")
    report = _ui.Report()

    if not skip_web:
        _ui.section("Web client (app/client-web)")
        web = client_dir()
        installed = True
        if not (web / "node_modules").is_dir():
            _ui.info("Installing web client dependencies (first run)…")
            installed = run(["npm", "ci"], cwd=web) == 0
            report.record("npm ci (web dependencies)", installed)
        if installed:
            report.step("tsc (web type-check)", lambda: run(["npx", "--no-install", "tsc", "-b"], cwd=web))
            report.step("eslint (web lint)", lambda: run(["npx", "--no-install", "eslint", "."], cwd=web))

    _ui.section("Python (the uv workspace)")
    # `--check` never writes; `--offline` keeps the pre-push hook off the network.
    # The desktop package's own desktop/uv.lock is outside the workspace and not checked.
    if (root / "uv.lock").is_file():
        report.step("uv lock --check (deps vs lockfile)", lambda: run(["uv", "lock", "--check", "--offline"], cwd=root))

    linted = list(python_files(root, LINTED))
    if not linted:
        _ui.info("(no Python files found)")
    else:
        report.record("syntax (Python, " + " ".join(f"{d}/" for d in LINTED) + ")", _syntax_step(linted, root))
        desktop = list(python_files(root, SYNTAX_ONLY))
        if desktop:
            report.record("syntax (older pswamp desktop/src/, syntax only)", _syntax_step(desktop, root))
        # ruff is pinned in the server's dev group and locked, so everyone runs the
        # identical linter. --select F is explicit and deliberately narrow.
        ruff = uv_server("--only-group", "dev", "ruff", "check", "--select", "F", *LINTED)
        report.step("ruff check (Python lint)", lambda: run(ruff, cwd=root))

    _ui.section("Pipelines (pipelines/*.toml)")
    report.step("pipelines validate (pipeline files load)", lambda: validate_files(pipeline_files(root)))

    _ui.section("Api contract")
    report.step("api contract (spec matches code)", lambda: contract.generate(check=True))

    raise typer.Exit(
        report.finish(
            "All checks passed.",
            f"If it was the api contract: {contract.REGENERATE_HINT}",
        )
    )
