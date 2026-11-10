"""Extra modules: a module developed outside this repo, run in the full local stack.

``pswamp dev server --extra-modules PATH`` takes a Python project (a folder with a
``pyproject.toml``), or a folder of them, whose modules are declared as
``[project.entry-points."pswamp.modules"]`` like any module project here. It then
runs the stack from the resolved compose configuration (``compose config``, the
override included), changed so that:

- every service built from the image is built with PATH as the ``extra-modules``
  build context, which the Dockerfile installs (its stage of that name);
- each of them has ``<APP>_EXTRA_MODULES`` set, which adds the modules to the
  pipeline file ``pipelines/<app>.toml`` wherever it is loaded (the server, the
  workers): ``pswamp_core.pipeline_config.extra_modules``;
- an ``extra-modules-worker`` (the ``module-worker`` service, copied) hosts those
  modules and nothing else, restarting on an edit of their ``src/`` (compose
  watch) and rebuilding on an edit of their ``pyproject.toml``.

Nothing here is committed or written into the repo: the configuration lives in a
temporary file for as long as the stack runs.
"""

from __future__ import annotations

import copy
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CONTAINER_ROOT",
    "CONTEXT",
    "WORKER",
    "ExtraModulesError",
    "ExtraProject",
    "read_extra_modules",
    "variable_for",
    "with_extra_modules",
]

#: Where the Dockerfile puts the extra-modules context, and installs it from.
CONTAINER_ROOT = "/workspace/extra-modules"
#: The build context's name: the Dockerfile's stage it replaces.
CONTEXT = "extra-modules"
#: The service that hosts the extra modules, and the one it is copied from.
WORKER = "extra-modules-worker"
TEMPLATE_WORKER = "module-worker"
MODULES_GROUP = "pswamp.modules"


class ExtraModulesError(ValueError):
    """The extra modules cannot be used as given; the message says why."""


@dataclass(frozen=True)
class ExtraProject:
    """One project with modules: where it is here and in the container, and its modules' names."""

    host: Path
    container: str
    modules: tuple[str, ...]


def _modules_of(manifest: Path) -> tuple[str, ...]:
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ExtraModulesError(f"{manifest}: {error}") from error
    return tuple(data.get("project", {}).get("entry-points", {}).get(MODULES_GROUP, {}))


def read_extra_modules(path: Path, repo: Path) -> list[ExtraProject]:
    """The projects at ``path``: the project there, or each folder below it that is one.

    Raises ``ExtraModulesError`` when there is none, none declares a module, or a module's name is
    one this repo's ``modules/`` already installs (two entry points of one name: which one loads is
    up to chance)."""
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise ExtraModulesError(f"{path} is not a folder")
    if (path / "pyproject.toml").is_file():
        found = [(path, CONTAINER_ROOT)]
    else:
        found = [
            (sub, f"{CONTAINER_ROOT}/{sub.name}")
            for sub in sorted(path.iterdir())
            if sub.is_dir() and (sub / "pyproject.toml").is_file()
        ]
    if not found:
        raise ExtraModulesError(f"{path} holds no pyproject.toml, neither itself nor in a folder below it")
    projects = [ExtraProject(host, container, _modules_of(host / "pyproject.toml")) for host, container in found]
    projects = [p for p in projects if p.modules]
    if not projects:
        raise ExtraModulesError(
            f'no project at {path} declares a module: add one under [project.entry-points."{MODULES_GROUP}"]'
        )
    ours = {name for manifest in (repo / "modules").glob("*/pyproject.toml") for name in _modules_of(manifest)}
    clashes = sorted(ours.intersection(name for p in projects for name in p.modules))
    if clashes:
        raise ExtraModulesError(f"{', '.join(clashes)}: already a module of this repo (modules/); rename the extra one")
    return projects


def variable_for(app: str) -> str:
    """``<APP>_EXTRA_MODULES``, spelled as ``pswamp_core.settings.env_key`` spells it."""
    return re.sub(r"[^A-Za-z0-9]+", "_", app).strip("_").upper() + "_EXTRA_MODULES"


def _watch(service: dict[str, Any]) -> list[dict[str, Any]]:
    return service.setdefault("develop", {}).setdefault("watch", [])


def with_extra_modules(config: dict[str, Any], context: Path, projects: list[ExtraProject], app: str) -> dict[str, Any]:
    """``config`` (``compose config --format json``) changed to run ``projects``' modules in the
    pipeline ``app``, built from ``context`` (the path given). A new dict; ``config`` is untouched.

    Raises ``ExtraModulesError`` when there is no ``module-worker`` to copy, or a service named
    ``extra-modules-worker`` already."""
    config = copy.deepcopy(config)
    services: dict[str, dict[str, Any]] = config.get("services", {})
    if TEMPLATE_WORKER not in services:
        raise ExtraModulesError(f"the compose file has no {TEMPLATE_WORKER} service to copy the worker from")
    if WORKER in services:
        raise ExtraModulesError(f"the compose file already has a service named {WORKER}")
    modules = ",".join(name for p in projects for name in p.modules)
    variable = variable_for(app)
    template = copy.deepcopy(services[TEMPLATE_WORKER])

    for service in services.values():
        if "build" not in service:
            continue
        service["build"].setdefault("additional_contexts", {})[CONTEXT] = str(context)
        service.setdefault("environment", {})[variable] = modules
        if service.get("develop"):
            # Kept in step (no restart): only the extra worker hosts the modules, but every service
            # loads the pipeline, and so their classes, when it starts.
            _watch(service).extend(
                {"path": str(p.host / "src"), "action": "sync", "target": f"{p.container}/src"}
                for p in projects
                if (p.host / "src").is_dir()
            )

    worker = template
    worker["build"].setdefault("additional_contexts", {})[CONTEXT] = str(context)
    worker["environment"] = {
        **worker.get("environment", {}),
        variable: modules,
        "PSWAMP_WORKER_PIPELINES": f"{app}.toml",
        "PSWAMP_WORKER_MODULES": modules,
    }
    worker.pop("container_name", None)
    if worker.get("develop"):
        for p in projects:
            if (p.host / "src").is_dir():
                _watch(worker).append({"path": str(p.host / "src"), "action": "sync+restart", "target": f"{p.container}/src"})
            _watch(worker).append({"path": str(p.host / "pyproject.toml"), "action": "rebuild"})
    services[WORKER] = worker
    return config
