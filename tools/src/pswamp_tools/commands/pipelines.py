"""``pswamp pipelines``: the pipeline files, ``pipelines/<app>.toml``."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .. import _ui
from .._paths import repo_root
from .._proc import require_tools, run, uv_server
from .modules import CATALOGUE

app = typer.Typer(
    help=(
        "The pipeline files: one per app, pipelines/<app>.toml, naming its modules (by entry point), "
        "its sources and its enrichment. The server and the workers load them with Pipeline.load."
    ),
    no_args_is_help=True,
)


def pipeline_files(root: Path) -> list[Path]:
    """Every pipeline file in the repo's pipelines/ folder."""
    return sorted((root / "pipelines").glob("*.toml"))


def validate_files(paths: list[Path]) -> int:
    """Load and check ``paths`` in the server's environment; the exit code."""
    if not paths:
        _ui.info("(no pipeline file to validate)")
        return 0
    root = repo_root()
    # Run from the repo root, so a file in it is named relative to it.
    names = [path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path) for path in paths]
    return run(uv_server(*CATALOGUE, "validate", *names), cwd=root)


@app.command()
def validate(
    paths: Optional[list[Path]] = typer.Argument(
        None, help="Pipeline files to check. Default: every pipelines/*.toml in the repo."
    ),
) -> None:
    """Load each pipeline file as the server and the workers do, and run every check.

    A file fails when it is not valid TOML or does not match the schema, names a
    module that is not installed, names a data client that does not import, or
    the pipeline it declares is inconsistent: two receivers of one command, two
    classes on one topic, a command a module sends that nothing takes, or a class
    a module reads that nothing produces. The environment applies, as it does at
    run time (<APP>_DATA_CLIENTS replaces a file's sources). Exits non-zero if any
    file fails.
    """
    require_tools("uv", purpose="for the server environment")
    raise typer.Exit(validate_files([path.resolve() for path in paths] if paths else pipeline_files(repo_root())))
