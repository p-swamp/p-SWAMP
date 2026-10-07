# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""What the excursion module (``excursion``) publishes, and the command it takes."""

from .commands import AutoPauseCommand
from .results import Excursion, ExcursionResult

__all__ = ["AutoPauseCommand", "Excursion", "ExcursionResult"]
