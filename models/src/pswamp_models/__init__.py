# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Every message that crosses a topic, a socket or a process boundary.

One package per producer: who publishes a message is where its class lives,
and the package is the namespace to import it from.

- ``common``: the bases every message builds on (``DataModel``, ``Command``,
  ``ResultEnvelope``) and the pipeline's own ``ErrorEvent`` and ``PipelineClosed``.
- ``player``: the player's commands and its ``PlayerStatus``.
- ``pmu``: ``PmuFrame`` and its ``PmuHeader``, what every PMU source publishes.
- ``remote_data``: the request and response lines of the remote data contract.
- ``frame_stats``, ``excursion``, ``range_summary``: what each of those modules
  publishes, and the commands it takes. A module's code imports its messages
  from here, and so does everyone else: nobody imports a module for its data.

Depends on pydantic only, so anything may depend on it: the core, the
modules, the web backend, a data provider outside this repo.
"""

__version__ = "0.1.0"
