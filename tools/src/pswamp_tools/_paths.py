"""Where the repo is, and the paths in it every command needs.

The CLI can be started from any directory inside the repo (``uv run pswamp`` in
``core/`` works as well as at the root), so nothing here is relative to the
working directory. The root is the first directory, walking up from the working
directory, that is the uv workspace root of *this* repo; failing that, the one
this package was installed (editable) from.
"""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path


class RepoNotFound(RuntimeError):
    """Raised when neither the working directory nor this package is in the repo."""


def is_repo_root(path: Path) -> bool:
    """True if ``path`` is the p-SWAMP workspace root.

    The test is the workspace table in its ``pyproject.toml`` plus the server
    member beside it — a bare ``pyproject.toml`` would also match any member.
    """
    manifest = path / "pyproject.toml"
    if not manifest.is_file() or not (path / "app" / "server-python").is_dir():
        return False
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return "workspace" in data.get("tool", {}).get("uv", {})


def find_repo_root(start: Path | None = None) -> Path:
    """The repo root, searched upward from ``start`` (default: the cwd), then from this file."""
    candidates = [Path.cwd() if start is None else start, Path(__file__)]
    for origin in candidates:
        origin = origin.resolve()
        for path in (origin, *origin.parents):
            if is_repo_root(path):
                return path
    raise RepoNotFound(
        "could not find the p-SWAMP repo root (a pyproject.toml with [tool.uv.workspace] "
        "beside app/server-python/). Run pswamp from inside the repo."
    )


@cache
def repo_root() -> Path:
    """The repo root, found once per process."""
    return find_repo_root()


def server_dir() -> Path:
    return repo_root() / "app" / "server-python"


def client_dir() -> Path:
    return repo_root() / "app" / "client-web"


def desktop_dir() -> Path:
    return repo_root() / "desktop"


def e2e_dir() -> Path:
    return repo_root() / "e2e"
