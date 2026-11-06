# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The CIM graph: the grid every module can read, and the measurements that tie a frame or a scan to it.

Needs the ``[cim]`` extra (LazyCIM). The store and how to read it is ``store``;
what is loaded into it, ``grid``; its PMU and SCADA measurements, ``measurements``;
where it all is, ``settings``; readying a script's own repository, ``prepare``;
keeping every reader's repository up to date, ``watch``.
A module reads the graph through the repository its host gives it (``Module.cim``),
never through a store of its own, or through one a script hands it, and the core keeps
that repository up to date before each call.
"""

from .limits import current_limits
from .measurements import SOURCES, add_measurements, has_measurements, measurement_table, station_name
from .grid import SAMPLE_GRID, Grid, stage
from .prepare import prepare
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
    "SOURCES",
    "add_measurements",
    "current_limits",
    "has_measurements",
    "measurement_table",
    "station_name",
    "connect_reader",
    "model_id",
    "open_store",
    "prepare",
    "refresh_expired",
    "stage",
]
