# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The CIM graph: the grid every module can read, and the PMU Analogs that tie a frame to it.

Needs the ``[cim]`` extra (LazyCIM). The store and how to read it is ``store``;
what is loaded into it, ``grid``; the PMU Analogs and their names, ``analogs``;
where it all is, ``settings``; keeping every reader's repository up to date, ``watch``.
A module reads the graph through the repository its host gives it (``Module.cim``),
never through a store of its own, and the core keeps that repository up to date
before each call.
"""

from .analogs import add_pmu_analogs, analog_index, analog_name, analog_table
from .grid import SAMPLE_GRID, Grid, stage
from .settings import CimSettings
from .store import (
    GraphVersion,
    LocalStore,
    ReadOnlyRepository,
    Store,
    connect_reader,
    model_id,
    open_store,
    refresh_expired,
)
from .watch import Freshness, GraphWatch

__all__ = [
    "SAMPLE_GRID",
    "CimSettings",
    "Freshness",
    "Grid",
    "GraphVersion",
    "GraphWatch",
    "LocalStore",
    "ReadOnlyRepository",
    "Store",
    "add_pmu_analogs",
    "analog_index",
    "analog_name",
    "analog_table",
    "connect_reader",
    "model_id",
    "open_store",
    "refresh_expired",
    "stage",
]
