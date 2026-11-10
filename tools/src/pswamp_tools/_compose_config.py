"""The stack's compose configuration, with compose files from outside the repo added.

``pswamp dev server --compose-file PATH`` adds a file after the repo's own
(``docker-compose.yml``, and ``docker-compose.override.yml`` when there is one),
as ``docker compose -f`` would, with one difference: a relative path in it is
relative to **its own folder**, not to the repo. Plain ``-f`` resolves every file's
paths against the project directory (the repo), so an override kept in another
project, mounting ``./grids``, would mount the repo's ``grids/``.

So each added file is first resolved alone, against its own folder
(``compose config --no-consistency``, which allows a file that only overrides),
and the absolute-path result, less the defaults compose fills in, is what joins
the repo's files.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from ._docker import Engine
from ._proc import capture

__all__ = ["ComposeConfigError", "repo_compose_files", "resolve", "strip_normalisation"]


class ComposeConfigError(RuntimeError):
    """``compose config`` refused a file; the message is compose's."""


def repo_compose_files(repo: Path) -> list[Path]:
    """The files compose reads in the repo by default: the base file, then the override if any."""
    return [path for path in (repo / "docker-compose.yml", repo / "docker-compose.override.yml") if path.is_file()]


def strip_normalisation(config: dict[str, Any]) -> dict[str, Any]:
    """``config`` (one file, resolved alone) without what compose fills in on its own: the project's
    name, its default network, and every service's unset keys (``command: null``) and default network.
    Merged as they are, those would clear what the repo's files set."""
    config = copy.deepcopy(config)
    config.pop("name", None)
    networks = config.get("networks")
    if isinstance(networks, dict):
        networks.pop("default", None)
        if not networks:
            config.pop("networks")
    for service in config.get("services", {}).values():
        for key in [key for key, value in service.items() if value is None]:
            del service[key]
        if service.get("networks") == {"default": None}:
            del service["networks"]
    return config


def _config(engine: Engine, args: list[str], cwd: Path, *, partial: bool = False) -> dict[str, Any]:
    """``compose <args> config``, as a dict; ``partial`` allows a file that only overrides."""
    flags = ("--no-consistency",) if partial else ()
    result = capture(engine.compose_cmd(*args, "config", *flags, "--format", "json"), cwd=cwd, timeout=120)
    if result.returncode != 0:
        raise ComposeConfigError((result.stderr or result.stdout).strip())
    return json.loads(result.stdout)


def resolve(engine: Engine, repo: Path, added: list[Path], scratch: Path) -> dict[str, Any]:
    """The repo's configuration with ``added`` merged in, in order, each file's relative paths taken
    from its own folder. ``scratch`` is a folder for the intermediate files."""
    files = repo_compose_files(repo)
    for n, path in enumerate(added):
        path = path.expanduser().resolve()
        if not path.is_file():
            raise ComposeConfigError(f"{path}: no such file")
        alone = _config(engine, ["-f", str(path), "--project-directory", str(path.parent)], cwd=path.parent, partial=True)
        piece = scratch / f"added-{n}-{path.stem}.json"
        piece.write_text(json.dumps(strip_normalisation(alone), indent=1), encoding="utf-8")
        files.append(piece)
    return _config(engine, [arg for f in files for arg in ("-f", str(f))] + ["--project-directory", str(repo)], cwd=repo)
