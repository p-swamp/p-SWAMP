"""The published api contract: generate it, or check the committed copy is current.

Two committed artifacts, both generated from the server's own document:

* ``doc/api/openapi.json`` — the contract, from ``app/server-python/tools/dump_openapi.py``;
* ``app/client-web/src/api/schema.ts`` — its TypeScript, from ``openapi-typescript``.

The document is dumped by running ``dump_openapi.py`` in the server's
environment (``uv run --project app/server-python``) rather than importing the
server into this process: the server package is not importable as a library
(``src/`` is a plain folder that ``dump_openapi.py`` puts on ``sys.path``), and
the subprocess makes the result independent of which environment ``pswamp`` was
launched from. Cost: one extra uv start, well under a second when warm.

The check compares with line endings normalised. With ``core.autocrlf=true``
(the Windows default) git checks the committed files out with CRLF, while the
generators write LF; byte-for-byte, every Windows checkout would be "stale".
"""

from __future__ import annotations

import difflib
import tempfile
from pathlib import Path

from . import _ui
from ._paths import client_dir, repo_root, server_dir
from ._proc import capture, require_tools, run, uv_server

SPEC = Path("doc/api/openapi.json")
TYPES = Path("app/client-web/src/api/schema.ts")
REGENERATE_HINT = "Regenerate and commit it:\n  uv run pswamp api generate"
DIFF_LINES = 40


def normalise(text: str) -> str:
    """``text`` with CRLF / CR line endings turned into LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def stale_diff(committed: Path, fresh: Path, label: str, limit: int = DIFF_LINES) -> list[str] | None:
    """``None`` if the two files match ignoring line endings, else the first lines of a unified diff."""
    a, b = normalise(read_text(committed)), normalise(read_text(fresh))
    if a == b:
        return None
    diff = difflib.unified_diff(
        a.splitlines(keepends=True), b.splitlines(keepends=True), f"{label} (committed)", f"{label} (generated)"
    )
    lines = [line.rstrip("\n") for line in diff]
    if len(lines) > limit:
        lines = [*lines[:limit], f"... ({len(lines) - limit} more diff lines)"]
    return lines


def _generator_installed() -> bool:
    bin_dir = client_dir() / "node_modules" / ".bin"
    return any((bin_dir / name).exists() for name in ("openapi-typescript", "openapi-typescript.cmd"))


def _write(spec_out: Path, types_out: Path) -> bool:
    """Dump the document to ``spec_out`` and its TypeScript to ``types_out``."""
    root = repo_root()
    dump = server_dir() / "tools" / "dump_openapi.py"
    if run(uv_server("python", str(dump), str(spec_out)), cwd=root) != 0:
        _ui.error("dumping the openapi document failed (see the output above)")
        return False
    types_out.parent.mkdir(parents=True, exist_ok=True)
    # openapi-typescript emits types only (no runtime, no `enum`). Run from
    # app/client-web so `npx --no-install` resolves the pinned devDependency and
    # errors rather than downloading on a miss; hence the absolute paths.
    code = run(
        ["npx", "--no-install", "openapi-typescript", str(spec_out.resolve()), "-o", str(types_out.resolve())],
        cwd=client_dir(),
        quiet=True,
    )
    if code != 0:
        _ui.error("openapi-typescript failed (see the output above)")
        return False
    return True


def generate(check: bool = False) -> int:
    """Regenerate both artifacts in place, or (``check``) compare fresh copies with them. Returns an exit code."""
    require_tools("uv", "npx", "npm", purpose="to generate the api contract")
    root = repo_root()
    if not _generator_installed():
        _ui.info("Installing web client dependencies (generator unavailable)…")
        if run(["npm", "ci"], cwd=client_dir()) != 0:
            _ui.error("npm ci failed in app/client-web")
            return 1

    if not check:
        if not _write(root / SPEC, root / TYPES):
            return 1
        if capture(["git", "diff", "--quiet", "--", str(SPEC), str(TYPES)], cwd=root).returncode == 0:
            _ui.console.print("No changes in api contract -> no changes in clientside schemas")
        else:
            _ui.console.print("Updated api contract json and clientside schema to match python source.\n\ncurrent diff:")
            run(["git", "--no-pager", "diff", "--stat", "--", str(SPEC), str(TYPES)], cwd=root)
        return 0

    with tempfile.TemporaryDirectory(prefix="pswamp-contract-") as tmp:
        fresh_spec, fresh_types = Path(tmp) / "openapi.json", Path(tmp) / "schema.ts"
        if not _write(fresh_spec, fresh_types):
            return 1
        stale = False
        for committed, fresh in ((SPEC, fresh_spec), (TYPES, fresh_types)):
            path = root / committed
            label = committed.as_posix()
            if not path.is_file():
                _ui.console.print(f"[red]  {label} is missing[/red]")
                stale = True
                continue
            diff = stale_diff(path, fresh, label)
            if diff is not None:
                _ui.console.print(f"[red]  {label} is out of date:[/red]")
                for line in diff:
                    _ui.console.print(line, markup=False)
                stale = True
    if stale:
        _ui.console.print(f"\nThe api contract does not match the code. {REGENERATE_HINT}")
        return 1
    _ui.info(f"{SPEC.as_posix()} and {TYPES.as_posix()} match the code.")
    return 0
