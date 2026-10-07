"""``pswamp new``: scaffold a subapp or a module (were generate-new-subapp.sh and
generate-new-module-with-frontend.sh)."""

from __future__ import annotations

import typer

from .. import _ui, contract, generate
from .._paths import repo_root
from .._proc import require_tools, run

app = typer.Typer(
    help=(
        "Scaffold a new app, wired into the nav, the route table, the ws/api path tables and the "
        "backend APPS registry. What comes out already works; replacing the placeholder is the work "
        "left. The files come from tools/src/pswamp_tools/templates/ (edit those, not the "
        "generator, to change what a new app starts life as; templates/README.md explains them)."
    ),
    no_args_is_help=True,
)

SLUG_HELP = "The url-name: lowercase words joined by hyphens, max 32 chars (e.g. grid-overview)."
LABEL_HELP = 'The nav label, a short human phrase (e.g. "Grid Overview").'
NO_CHECK_HELP = (
    "Skip the `pswamp check` run at the end. The api contract is regenerated anyway: "
    "a stale one would just leave a broken tree."
)


def _generate(slug: str, label: str, template_set: str, no_check: bool) -> None:
    root = repo_root()
    try:
        plan = generate.plan(root, slug, label, template_set)
    except generate.GenerateError as exc:
        _ui.error(str(exc))
        raise typer.Exit(1) from None
    if template_set == "module":
        require_tools("uv", purpose="to add the module project to the workspace lock")
    generate.apply(plan, echo=lambda line: _ui.console.print(line, markup=False))
    _ui.console.print(f"\n[bold]{generate.summary(plan)}[/bold]", markup=True)
    _ui.info("the api contract is regenerated next — commit doc/api/openapi.json and")
    _ui.info("app/client-web/src/api/schema.ts along with the new app.")

    # A module is a new workspace member (modules/*) and a new dependency of the
    # wiring and the server, so the one uv.lock must learn of it before anything
    # runs `uv run` (which would re-lock implicitly) or `uv lock --check`.
    if template_set == "module":
        _ui.section("Re-lock the workspace (uv lock)")
        code = run(["uv", "lock"], cwd=root)
        if code != 0:
            raise typer.Exit(code)

    # The contract BEFORE the checks: the new page imports its wire type from the
    # TypeScript generated off the new package's WS_MESSAGE, so until this runs
    # the app does not type-check. Runs even with --no-check.
    _ui.section("Regenerate the api contract")
    code = contract.generate(check=False)
    if code != 0:
        raise typer.Exit(code)

    if not no_check:
        from .check import check

        try:
            check(skip_web=False)
        except typer.Exit as exc:
            if exc.exit_code:
                raise

    _ui.console.print(
        "\nRestart `uv run pswamp dev server` — a new Python package needs the rebuild, "
        "not just compose watch — and the page is in the nav.",
        markup=False,
    )


@app.command()
def subapp(
    slug: str = typer.Argument(..., help=SLUG_HELP),
    label: str = typer.Argument(..., help=LABEL_HELP),
    no_check: bool = typer.Option(False, "--no-check", envvar="NO_CHECK", help=NO_CHECK_HELP),
) -> None:
    """A page and its api: a per-client counter (POST to bump it, the socket to see it).

    Writes app/server-python/src/<pkg>/ and app/client-web/src/pages/<slug>/,
    registers both (server.py APPS, App.tsx route, AppLayout.tsx nav,
    lib/servers.ts paths), regenerates the api contract and runs `pswamp check`.
    Writes nothing if the name is taken or invalid.

      uv run pswamp new subapp grid-overview "Grid Overview"
    """
    _generate(slug, label, "subapp", no_check)


@app.command()
def module(
    slug: str = typer.Argument(..., help=SLUG_HELP),
    label: str = typer.Argument(..., help=LABEL_HELP),
    no_check: bool = typer.Option(False, "--no-check", envvar="NO_CHECK", help=NO_CHECK_HELP),
) -> None:
    """A module over the core pipeline, and the page that shows it.

    The module is a project of its own, modules/<slug>/ (pyproject.toml with
    its `pswamp.modules` entry point, README.md, src/pswamp_modules/<pkg>/,
    tests/); its messages go to models/src/pswamp_models/<pkg>/ and its
    pipeline to the transitional legacy/pswamp-wiring/; the web api to
    app/server-python/src/<pkg>/ and the page to app/client-web/src/pages/<slug>/.
    The project becomes a dependency of the wiring and the server, the
    workspace is re-locked (`uv lock`), and the module is added to the
    module-worker in docker-compose.yml and k8s/p-swamp-local.yaml.
    doc/module-cookbook.md walks through every file; `pswamp check-generators`
    proves the output works.

      uv run pswamp new module peak-frequency "Peak frequency"
    """
    _generate(slug, label, "module", no_check)
