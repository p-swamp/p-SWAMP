# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``Command``: the base of every typed message going upstream.

**A command's class is its address.** Each class travels on its own topic
(``SeekCommand`` → ``<app>.seek.command``), and exactly one part of a pipeline
declares that it handles it: the player, or one module. Anyone may publish a
command (the web API, a module); anyone may subscribe to its topic to watch. The
fields are the arguments, validated where the command is built.

The commands themselves live with whoever receives them: the player's in
``pswamp_models.player``, a module's in its own producer folder.

``request_id`` is generated when a command is built. Whatever answers the
command carries it: a module's result, or an ``ErrorEvent`` if it was refused.
"""

from __future__ import annotations

from typing import ClassVar, Literal
from uuid import uuid4

from pydantic import Field

from .data_model import DataModel, topic_from_name

__all__ = ["Command"]


class _Name:
    """``Command.name``: the class name without ``Command``, dotted:
    ``SwitchSourceCommand`` → ``switch.source``. What logs and acks call it."""

    def __get__(self, instance: object, owner: type[Command]) -> str:
        return topic_from_name(owner.__name__.removesuffix("Command") or owner.__name__)


class Command(DataModel):
    """One upstream action. Subclass it; the subclass is the address."""

    version: Literal["v1"] = "v1"
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    client_id: str | None = Field(default=None, description="The client that issued it, if any.")

    name: ClassVar[_Name] = _Name()
