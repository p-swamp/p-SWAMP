# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The live simulation's commands, each addressed to it by its class.

Every command names the CIM object it acts on by ``mRID``: a switch, a line or
transformer, a connectivity node, a load. The simulation is their one receiver.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..common.command import Command

__all__ = [
    "DISTURBANCES",
    "OPERATIONS",
    "RTSIM_COMMANDS",
    "ClearShortCircuitCommand",
    "FaultAndClearCommand",
    "LoadStepCommand",
    "OperateLineCommand",
    "OperateSwitchCommand",
    "ReconnectBranchCommand",
    "ResetSimulationCommand",
    "RtsimCommand",
    "ShortCircuitCommand",
    "TripBranchCommand",
]


class RtsimCommand(Command):
    """Base of the commands the live simulation handles."""


class _OnObject(RtsimCommand):
    mRID: str = Field(description="The CIM object it acts on.")


# -- operations: their result is reported to the CIM graph --------------------


class OperateSwitchCommand(_OnObject):
    """Open or close a breaker (any switch)."""

    open: bool


class OperateLineCommand(_OnObject):
    """Take a line that has no breaker out of service, or bring it back, by its terminal."""

    in_service: bool


# -- disturbances: the CIM graph never hears of them --------------------------


class TripBranchCommand(_OnObject):
    """A line or transformer trips, as no one commanded it."""


class ReconnectBranchCommand(_OnObject):
    """A tripped line or transformer comes back."""


class ShortCircuitCommand(_OnObject):
    """A short circuit at a connectivity node, through an admittance to ground."""

    y: float = Field(default=1e6, gt=0, description="The fault's admittance, per unit; the default is bolted.")


class ClearShortCircuitCommand(_OnObject):
    """The short circuit at a connectivity node goes."""


class FaultAndClearCommand(_OnObject):
    """A fault at one end of a line, cleared by its protection.

    A short circuit at the bus of that end; after ``clear_ms`` the breakers that
    isolate the line open at both ends, and the fault goes. The breakers' new
    state is reported to the CIM graph, the fault is not.
    """

    end: Literal[1, 2] = Field(default=1, description="The line end the fault is at.")
    clear_ms: float = Field(default=100.0, gt=0, description="How long the protection takes to clear it, ms.")
    y: float = Field(default=1e6, gt=0, description="The fault's admittance, per unit.")


class LoadStepCommand(_OnObject):
    """A load draws other power, as no one told the CIM graph."""

    p_mw: float | None = Field(default=None, allow_inf_nan=False, description="Its new active power, MW.")
    q_mvar: float | None = Field(default=None, allow_inf_nan=False, description="Its new reactive power, Mvar.")

    @model_validator(mode="after")
    def _changes_something(self) -> LoadStepCommand:
        if self.p_mw is None and self.q_mvar is None:
            raise ValueError("a load step sets p_mw, q_mvar or both")
        return self


class ResetSimulationCommand(RtsimCommand):
    """Start the simulation over from the CIM graph, clearing every disturbance."""


OPERATIONS: tuple[type[RtsimCommand], ...] = (OperateSwitchCommand, OperateLineCommand)
DISTURBANCES: tuple[type[RtsimCommand], ...] = (
    TripBranchCommand,
    ReconnectBranchCommand,
    ShortCircuitCommand,
    ClearShortCircuitCommand,
    FaultAndClearCommand,
    LoadStepCommand,
)
#: Every command the live simulation takes.
RTSIM_COMMANDS: tuple[type[RtsimCommand], ...] = (*OPERATIONS, *DISTURBANCES, ResetSimulationCommand)
