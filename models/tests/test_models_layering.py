"""The bottom of the layering: the models import pydantic and the standard library only.

Every package under ``pswamp_models`` is imported in a fresh interpreter,
started from a neutral directory with no ``PYTHONPATH``; whatever third-party
top-level package ends up loaded must be pydantic or one of its own
dependencies. So a new producer folder is covered without an edit here, and a
model reaching for the core, a module or the web backend fails.
"""

from __future__ import annotations

import os
import subprocess
import sys

# pydantic and what pydantic itself imports.
ALLOWED = {"pswamp_models", "pydantic", "pydantic_core", "typing_extensions", "annotated_types", "typing_inspection"}

# What was loaded before the import (the interpreter's own start-up, a venv's
# site hooks) is not the models' doing, so only what the import adds counts.
IMPORT_ALL = """
import importlib, pkgutil, sys
def top():
    return {{name.partition(".")[0] for name in sys.modules}}
before = top()
package = importlib.import_module("pswamp_models")
for found in pkgutil.walk_packages(package.__path__, "pswamp_models."):
    importlib.import_module(found.name)
foreign = sorted(top() - before - set(sys.stdlib_module_names) - {allowed!r})
assert not foreign, f"pswamp_models imports {{foreign}}"
"""


def test_the_models_import_pydantic_only(tmp_path):
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    code = IMPORT_ALL.format(allowed=ALLOWED)
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
