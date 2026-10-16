"""``pswamp modules``: the installed modules, as a pipeline file finds them."""

from __future__ import annotations

import typer

from .._paths import repo_root
from .._proc import require_tools, run, uv_server

app = typer.Typer(
    help=(
        "The installed modules: what a pipeline file (pipelines/<app>.toml) can name in its `modules` list. "
        "A module is found by its entry point in the `pswamp.modules` group, which its project declares."
    ),
    no_args_is_help=True,
)

# The listing itself is pswamp_core's, run in the server's environment (where
# every module project is installed): the CLI imports nothing from the members.
CATALOGUE = ("python", "-m", "pswamp_core.pipeline_config")


@app.command("list")
def list_modules() -> None:
    """Every installed module: its name, kind, what it reads and emits, the commands it takes, its distribution.

    Exits non-zero if a module's entry point does not resolve to a Module of the same name.
    """
    require_tools("uv", purpose="for the server environment")
    raise typer.Exit(run(uv_server(*CATALOGUE, "modules"), cwd=repo_root()))
