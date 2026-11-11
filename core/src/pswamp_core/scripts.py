# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""A module or a source, by its name, for a plain script.

A module imports no other module (``tools/tests/test_tools_layering.py``), and its examples keep to
the same rule: an example of ``frame-stats`` that wants the live grid simulation's frames names the
source, ``source("rtsim-from-cim", ...)``, and its project declares, as an extra, the project that
provides it. The name is the ``pswamp.modules`` entry point, as in a pipeline file.

    from pswamp_core.scripts import source
    for frame in source("sample-replay").read():
        ...
"""

from __future__ import annotations

from typing import Any

from .modules import Module
from .pipeline_config import resolve_entry
from .sources import SourceModule

__all__ = ["module", "source"]


def module(name: str, **kwargs: Any) -> Module:
    """A new instance of the module installed as ``name``; ``kwargs`` go to its constructor."""
    return resolve_entry(name)(**kwargs)


def source(name: str, **kwargs: Any) -> SourceModule:
    """A new instance of the source installed as ``name``; ``kwargs`` go to its constructor.

    Raises ``PipelineConfigError`` when nothing is installed under that name (add the project that
    provides it, as an extra of your own), ``TypeError`` when it is a module but not a source."""
    found = resolve_entry(name)
    if not issubclass(found, SourceModule):
        raise TypeError(f"{name!r} is a module, not a source: use pswamp_core.scripts.module")
    return found(**kwargs)
