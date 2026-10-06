"""Which container engine is installed, and which compose command drives it.

Docker and Podman are both supported, including Podman installed *as*
``docker`` (a ``docker`` shim or alias whose ``docker --version`` says
"podman"). The compose command is the first of these that answers
``<cmd> version``:

* Docker: ``docker compose``, then ``docker-compose``;
* Podman: ``podman compose`` (which delegates to an installed provider), then
  ``podman-compose``, then ``docker-compose``.

Nothing found is a :class:`ContainerToolMissing` that says what was tried and
how to fix it, never a traceback.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from ._proc import INSTALL_HINTS, capture

# A cold `podman compose version` can start a provider; give it time.
PROBE_TIMEOUT = 30.0


class ContainerToolMissing(RuntimeError):
    """No usable container engine or compose command."""


@dataclass(frozen=True)
class Engine:
    """A container engine and the compose command that goes with it."""

    name: str  # "docker" or "podman": what the engine really is
    cli: str  # the executable to run for engine commands (`ps`, `rm`, `logs`)
    compose: tuple[str, ...]  # argv prefix for compose, e.g. ("docker", "compose")

    @property
    def is_podman(self) -> bool:
        return self.name == "podman"

    def compose_cmd(self, *args: str) -> list[str]:
        return [*self.compose, *args]


def _answers(argv: list[str]) -> tuple[bool, str]:
    """Whether ``argv`` runs and exits 0, plus its combined output."""
    try:
        result = capture(argv, timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return result.returncode == 0, (result.stdout or "") + (result.stderr or "")


def detect_engine() -> tuple[str, str]:
    """``(name, cli)`` of the installed engine: docker first, then podman.

    A ``docker`` that reports itself as podman is podman (name ``"podman"``) run
    through the ``docker`` executable.
    """
    docker = shutil.which("docker")
    if docker is not None:
        works, output = _answers([docker, "--version"])
        if works:
            return ("podman" if "podman" in output.lower() else "docker"), docker
    podman = shutil.which("podman")
    if podman is not None:
        works, _ = _answers([podman, "--version"])
        if works:
            return "podman", podman
    raise ContainerToolMissing(
        "no container engine found: neither `docker` nor `podman` is on PATH (or neither runs).\n"
        f"  -> {INSTALL_HINTS['docker']}"
    )


def _compose_candidates(name: str, cli: str) -> list[list[str]]:
    candidates: list[list[str]] = [[cli, "compose"]]
    if name == "podman":
        candidates += [[path] for tool in ("podman-compose", "docker-compose") if (path := shutil.which(tool))]
    else:
        candidates += [[path] for tool in ("docker-compose",) if (path := shutil.which(tool))]
    return candidates


def find_engine() -> Engine:
    """The engine plus a working compose command, or :class:`ContainerToolMissing`."""
    name, cli = detect_engine()
    tried: list[str] = []
    for candidate in _compose_candidates(name, cli):
        works, _ = _answers([*candidate, "version"])
        if works:
            return Engine(name=name, cli=cli, compose=tuple(candidate))
        tried.append(" ".join(candidate))
    hint = (
        "install the Docker Compose plugin (https://docs.docker.com/compose/install/)"
        if name == "docker"
        else "install podman-compose (`pip install podman-compose`) or docker-compose, "
        "and make sure the podman machine is running (`podman machine start`)"
    )
    raise ContainerToolMissing(
        f"found {name} ({cli}) but no working compose command; tried: {', '.join(tried) or 'nothing'}.\n"
        f"  -> {hint}"
    )
