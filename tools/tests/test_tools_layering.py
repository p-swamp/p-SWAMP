"""The layering: models <- core <- modules <- the web backend, over every module project.

Every ``modules/*/pyproject.toml`` is found, so a new module is covered with no
edit here. For each one:

* importing its package (every submodule of it) in a fresh interpreter, started
  from a neutral directory with no ``PYTHONPATH`` as a worker is, loads nothing
  from the web backend or the desktop package, and nothing outside the stdlib,
  the core, the models, its own package and its declared dependencies;
* its folder holds only module code: ``src/``, ``tests/``, ``examples/``,
  ``README.md`` and ``pyproject.toml``;
* its entry point in ``pswamp.modules`` names its own class, under its ``name``.

And the core imports no module. (The models' own rule, pydantic and the stdlib
only, is ``models/tests/test_models_layering.py``.)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "modules"
PROJECTS = sorted(path.parent for path in MODULES.glob("*/pyproject.toml"))

ALLOWED_ENTRIES = {"src", "tests", "examples", "README.md", "pyproject.toml"}
# Derived, never committed: caches, venvs, build output.
IGNORED_ENTRIES = {"__pycache__", ".venv", ".pytest_cache", ".ruff_cache", ".mypy_cache", "build", "dist"}
FORBIDDEN = {"fastapi", "starlette", "uvicorn", "server", "shared", "pswamp_web", "pswamp"}
# Every module may use these: the core and the models are its declared base.
BASE = {"pswamp_core", "pswamp_models"}
# What a declared dependency imports when it happens to be installed, though it
# does not require it: httpx loads its command line (click, rich, pygments) if present.
OPTIONAL_IMPORTS = {"httpx": {"click", "pygments", "rich"}}

# Run in the fresh interpreter: import the package and every submodule of it,
# then report the top-level names that the import added to sys.modules.
IMPORT_ALL = """
import importlib, json, pkgutil, sys
before = set(sys.modules)
package = importlib.import_module({package!r})
for found in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
    importlib.import_module(found.name)
added = set(sys.modules) - before
print(json.dumps(sorted(added)))
"""


def project_id(path: Path) -> str:
    return path.name


def manifest(project: Path) -> dict:
    return tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))


def package_of(project: Path) -> str:
    return manifest(project)["tool"]["uv"]["build-backend"]["module-name"]


def requirement_name(requirement: str) -> str:
    return re.split(r"[\s\[<>=!~;(]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")


def dependency_closure(names: set[str]) -> set[str]:
    """The distributions ``names`` need, transitively (extras-only requirements left out)."""
    from importlib import metadata

    seen: set[str] = set()
    todo = list(names)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        todo += [requirement_name(r) for r in requires if "extra ==" not in r.partition(";")[2]]
    return seen


def top_level_names(distributions: set[str]) -> set[str]:
    """The importable top-level names those distributions provide."""
    from importlib import metadata

    normal = {d.replace("_", "-") for d in distributions}
    return {
        top
        for top, providers in metadata.packages_distributions().items()
        if {p.lower().replace("_", "-") for p in providers} & normal
    }


def imported_by(package: str, cwd: Path) -> set[str]:
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, "-c", IMPORT_ALL.format(package=package)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return set(json.loads(done.stdout.strip().splitlines()[-1]))


def test_there_are_module_projects():
    assert {p.name for p in PROJECTS} >= {
        "frame-stats", "excursion", "range-summary", "sample-replay", "live-synthetic", "remote-history",
    }


@pytest.mark.parametrize("project", PROJECTS, ids=project_id)
def test_a_module_imports_only_its_declared_dependencies(project, tmp_path):
    package = package_of(project)
    assert package.startswith("pswamp_modules.") and package.count(".") == 1, package
    declared = {requirement_name(r) for r in manifest(project)["project"].get("dependencies", [])}
    closure = dependency_closure(declared)
    optional = set().union(*(OPTIONAL_IMPORTS.get(name, set()) for name in closure))
    allowed = BASE | top_level_names(closure) | optional | set(sys.stdlib_module_names)

    added = imported_by(package, tmp_path)
    tops = {name.partition(".")[0] for name in added}
    assert not tops & FORBIDDEN, f"{package} imports {sorted(tops & FORBIDDEN)}"
    # Private stdlib helpers (_decimal, _strptime, ...) are not in stdlib_module_names.
    strangers = sorted(t for t in tops - allowed - {"pswamp_modules"} if not t.startswith("_"))
    assert not strangers, f"{package} imports {strangers}, which it does not declare"
    others = sorted(
        name for name in added
        if name.startswith("pswamp_modules.") and not (name == package or name.startswith(package + "."))
    )
    assert not others, f"{package} imports other modules: {others}"


@pytest.mark.parametrize("project", PROJECTS, ids=project_id)
def test_a_module_folder_holds_only_module_code(project):
    entries = {entry.name for entry in project.iterdir()} - IGNORED_ENTRIES
    entries = {e for e in entries if not e.endswith(".egg-info")}
    assert entries <= ALLOWED_ENTRIES, f"{project.name}/ holds {sorted(entries - ALLOWED_ENTRIES)}"
    assert {"src", "tests", "README.md", "pyproject.toml"} <= entries
    namespace = project / "src" / "pswamp_modules"
    assert not (namespace / "__init__.py").exists(), "pswamp_modules is a namespace: no __init__.py"
    assert [p.name for p in namespace.iterdir() if p.name != "__pycache__"] == [package_of(project).split(".")[1]]


@pytest.mark.parametrize("project", PROJECTS, ids=project_id)
def test_a_module_s_entry_point_is_its_name(project):
    points = manifest(project)["project"]["entry-points"]["pswamp.modules"]
    assert len(points) == 1
    ((name, target),) = points.items()
    path, _, attribute = target.partition(":")
    assert path == package_of(project)
    import importlib

    module_class = getattr(importlib.import_module(path), attribute)
    assert module_class.name == name


def test_the_modules_folder_holds_only_module_projects():
    stray = sorted(
        entry.name
        for entry in MODULES.iterdir()
        if entry.is_dir() and entry.name not in IGNORED_ENTRIES and not (entry / "pyproject.toml").is_file()
    )
    assert not stray, f"modules/ holds folders that are not module projects: {stray}"


def test_the_core_imports_no_module(tmp_path):
    added = imported_by("pswamp_core", tmp_path)
    assert not any(name.partition(".")[0] == "pswamp_modules" for name in added)
