"""The layering: core <- modules <- the web backend.

Each check imports a whole package in a fresh interpreter, started from a
neutral directory with no ``PYTHONPATH``, as a worker is. It walks the
package, each module's ``tests/`` included, so a new module is covered without
an edit here.
"""

from __future__ import annotations

import os
import subprocess
import sys

IMPORT_ALL = """
import importlib, pkgutil, sys
package = importlib.import_module({package!r})
for found in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
    importlib.import_module(found.name)
loaded = sorted({forbidden!r} & {{name.partition(".")[0] for name in sys.modules}})
assert not loaded, f"{package} imports {{loaded}}"
"""


def import_all(package: str, forbidden: set[str], cwd) -> subprocess.CompletedProcess:
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    code = IMPORT_ALL.format(package=package, forbidden=forbidden)
    return subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True)


def test_modules_import_neither_the_web_backend_nor_the_desktop_package(tmp_path):
    forbidden = {"fastapi", "starlette", "uvicorn", "server", "shared", "pswamp_web", "pswamp"}
    done = import_all("pswamp_modules", forbidden, tmp_path)
    assert done.returncode == 0, done.stderr


def test_the_core_imports_no_module(tmp_path):
    done = import_all("pswamp_core", {"pswamp_modules"}, tmp_path)
    assert done.returncode == 0, done.stderr
