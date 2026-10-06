"""``pswamp api``: the published api contract (was scripts/generate-api-contract.sh)."""

from __future__ import annotations

import typer

from .. import contract

app = typer.Typer(
    help=(
        "The published api contract: doc/api/openapi.json and the TypeScript the web client "
        "reads it through (app/client-web/src/api/schema.ts). Both are generated from the "
        "server's own document and committed; regenerate them after changing an endpoint or "
        "a socket message."
    ),
    no_args_is_help=True,
)


@app.command()
def generate(
    check: bool = typer.Option(
        False,
        "--check",
        help="Read-only: generate into a temp dir and fail (exit 1, with a diff) if either committed "
        "file is stale. Line endings are ignored, so a CRLF checkout (core.autocrlf) is not stale.",
    ),
) -> None:
    """Regenerate doc/api/openapi.json and app/client-web/src/api/schema.ts from the server code.

    Runs app/server-python/tools/dump_openapi.py in the server's environment
    (it imports the FastAPI app but starts no server and binds no port), then
    openapi-typescript (the web client's pinned devDependency; `npm ci` first if
    it is missing). Commit both files with the api change.
    """
    raise typer.Exit(contract.generate(check=check))
