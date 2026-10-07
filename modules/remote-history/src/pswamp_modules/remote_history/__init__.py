# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The remote history source (``remote-history``): see ``source.py``. What it
publishes is in ``pswamp_models.pmu``; the wire to the service, in
``pswamp_models.remote_data``."""

from .source import RemoteHistory

__all__ = ["RemoteHistory"]
