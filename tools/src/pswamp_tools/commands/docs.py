"""``pswamp docs``: the documentation site (mkdocs.yml, built from doc/ and the module READMEs)."""

from __future__ import annotations

import typer

from .. import _ui
from .._paths import repo_root
from .._proc import require_tool, run

app = typer.Typer(
    help=(
        "The documentation site: mkdocs.yml at the repo root, built from doc/, every module's README "
        "and docs/, and the docstrings. `docs serve` previews it with live reload, `docs build` "
        "builds it as CI does (--strict: a broken link or an unresolved reference fails). The "
        "builders are the `docs` dependency group of pswamp-tools, installed on first use."
    ),
    no_args_is_help=True,
)

# Port 8000 is the dev server's (`pswamp dev server`), so the preview takes the next one.
PREVIEW_ADDR = "127.0.0.1:8001"

# Two plugins print a page-long banner about MkDocs' future on every run; the
# plan for that is in doc/project/deploying-docs.md, not in every build log.
QUIET_ENV = {"NO_MKDOCS_2_WARNING": "1", "DISABLE_MKDOCS_2_WARNING": "true"}


def mkdocs(*args: str) -> list[str]:
    """``mkdocs …`` in the workspace env, with the docs group (installed on first use)."""
    return ["uv", "run", "--package", "pswamp-tools", "--group", "docs", "mkdocs", *args]


@app.command()
def serve(
    no_browser: bool = typer.Option(
        False, "--no-browser", envvar="NO_BROWSER", help="Don't open the browser once the preview is up."
    ),
) -> None:
    """Preview the site on http://127.0.0.1:8001 and rebuild it on every edit (Ctrl-C stops it).

    Watches doc/, mkdocs.yml and every source outside doc/ the site is built from
    (the module READMEs and docs/, the Python packages' docstrings). Not strict, so
    a page in progress still renders; run `pswamp docs build` before a pull request.
    """
    require_tool("uv")
    _ui.info(f"Documentation preview on http://{PREVIEW_ADDR}/")
    argv = mkdocs("serve", "--dev-addr", PREVIEW_ADDR)
    if not no_browser:
        argv.append("--open")
    raise typer.Exit(run(argv, cwd=repo_root(), env=QUIET_ENV))


@app.command()
def build(
    strict: bool = typer.Option(
        True, "--strict/--no-strict", help="Fail on any warning: a broken link, an unresolved reference."
    ),
) -> None:
    """Build the site into site/ (gitignored), --strict by default, as the docs workflow does.

    Open site/index.html to read it, or use `pswamp docs serve`.
    """
    require_tool("uv")
    argv = mkdocs("build", *(["--strict"] if strict else []))
    raise typer.Exit(run(argv, cwd=repo_root(), env=QUIET_ENV))
