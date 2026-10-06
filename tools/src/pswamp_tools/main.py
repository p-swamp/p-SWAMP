"""The ``pswamp`` command: every piece of repo automation, one cross-platform CLI."""

from __future__ import annotations

import sys

import typer

from . import _ui
from ._docker import ContainerToolMissing
from ._paths import RepoNotFound
from ._proc import ToolMissing, repair_path
from .commands import api, dev, new, test
from .commands.check import HELP as CHECK_HELP
from .commands.check import check
from .commands.check_generators import HELP as CHECK_GENERATORS_HELP
from .commands.check_generators import check_generators

# Errors that are the environment's, not the code's: printed as one clear
# message with exit code 1, never as a traceback.
FRIENDLY_ERRORS = (ToolMissing, ContainerToolMissing, RepoNotFound)


class _App(typer.Typer):
    def __call__(self, *args, **kwargs):
        try:
            return super().__call__(*args, **kwargs)
        except FRIENDLY_ERRORS as exc:
            _ui.error(str(exc))
            sys.exit(1)


app = _App(
    name="pswamp",
    help=(
        "The p-SWAMP repo CLI: checks, the api contract and the test suites, on Windows, macOS and Linux.\n\n"
        "Run it as `uv run pswamp …` from anywhere in the repo. Every command and group has --help, "
        "and that help is the documentation. A missing tool (uv, node/npm/npx, docker/podman, git) "
        "is reported with how to install it."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
    add_completion=False,
)


@app.callback()
def _main() -> None:
    # A GUI git frontend (the pre-push hook) may start us with a minimal PATH.
    repair_path()


app.command("check", help=CHECK_HELP)(check)
app.add_typer(api.app, name="api")
app.add_typer(test.app, name="test")
app.add_typer(new.app, name="new")
app.command("check-generators", help=CHECK_GENERATORS_HELP)(check_generators)
app.add_typer(dev.app, name="dev")


if __name__ == "__main__":
    app()
