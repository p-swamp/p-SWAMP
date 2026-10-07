# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``AutoPauseCommand``: the excursion module's one command."""

from __future__ import annotations

from typing import Literal

from ..common.command import Command

__all__ = ["AutoPauseCommand"]


class AutoPauseCommand(Command):
    """Pause the player when the frequency leaves the band, or stop doing so."""

    version: Literal["v1"] = "v1"
    enabled: bool
