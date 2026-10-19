# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The RT sim (CIM) source (``rtsim-from-cim``): see ``source.py``. The graph it follows is the CIM
graph every module reads (``pswamp_core.cim``); ``follow.py`` keeps its TOPS export up to date,
``engine.py`` steps it, ``pmu.py`` measures it at the graph's PMU Analogs."""

from .source import RtsimFromCimSource

__all__ = ["RtsimFromCimSource"]
