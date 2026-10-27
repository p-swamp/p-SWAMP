"""The grid monitor's backend: the main window's panels, over the live grid.

Every panel is a view of one thing, the shared run of the grid-monitor pipeline
(``pipelines/grid-monitor.toml``: the simulation of the grid in the CIM graph, and the modules that
analyse it), which ``live.LIVE`` follows for the whole process. This package exports that
follower's ``lifespan`` and no router: server.py enters it as a service, before the apps, and mounts
its page packages -- app_status, grid, time_window, phasors, islanding, line_outage -- as apps of
their own, at the slugs the web client's grid monitor has always used.

The wire shapes are ``pswamp_web.wire``'s, which the web client's types are generated from.
"""

from .live import LIVE, lifespan

__all__ = ["LIVE", "lifespan"]
