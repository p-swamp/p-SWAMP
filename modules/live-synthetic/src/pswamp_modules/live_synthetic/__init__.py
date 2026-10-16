# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The synthetic live source (``live-synthetic``): see ``source.py``. What it
publishes is in ``pswamp_models.pmu``."""

from .source import LIVE_STREAM_ID, LiveSynthetic

__all__ = ["LIVE_STREAM_ID", "LiveSynthetic"]
