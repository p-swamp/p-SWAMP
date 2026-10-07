# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The PMU test streamer: the worked example of the server data architecture
(doc/server-data-architecture.md). This package is its web API (``api.py``).
Its modules are projects in ``modules/`` (``frame-stats``, ``excursion``,
``range-summary``); its pipeline and sources are in ``legacy/pswamp-wiring/``.

  router      the endpoints, mounted by server.py under /api/pmu-test-streamer
  lifespan    hosts the module in-process when there is no broker; stops the runs
  WS_MESSAGE  the model this app pushes down its socket
"""

from .api import PmuStreamState, lifespan, router

WS_MESSAGE = PmuStreamState

__all__ = ["WS_MESSAGE", "PmuStreamState", "lifespan", "router"]
