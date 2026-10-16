# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``DataModel``: the base of every message.

A message is a pydantic model, so its JSON is the whole codec:
``model_dump_json`` out, ``model_validate_json`` in. No pickle and no numpy on
the wire, so any message can be logged, validated on receipt, and published in
the browser's api contract as it is.

Every message has:

- ``version``: the schema version. A subclass pins it
  (``version: Literal["v1"] = "v1"``), so a ``"v2"`` payload fails validation
  instead of being half-read.
- ``mRID``: what the message is about (a stream, a station), in CIM's
  vocabulary. Optional.
- ``timestamp``: the instant the message refers to, always UTC.
- ``topic``: derived from the class name (``PmuFrame`` → ``pmu.frame``), so
  the message classes are the topic catalogue.

One thing it carries that is not a field: when a transport delivered it, the
wall-clock time it was sent (``sent_at``). It never serialises; a consumer
uses it to tell how far behind its input it runs (``pswamp_core.keep_up``).

Adapted from Louis Pauchet's test_pswamp draft (``core/models/data_model.py``).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, PrivateAttr, field_validator

from .utc import ensure_utc

__all__ = ["DataModel", "sent_at", "stamp_sent_at", "topic_from_name"]

# One word per run of capitals ending a word (an acronym), capitalised word, or
# digit run.
_CAMEL_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")


def topic_from_name(name: str) -> str:
    """``PmuFrame`` → ``pmu.frame``; ``FrameStatsResult`` → ``frame.stats.result``."""
    words = _CAMEL_WORDS.findall(name)
    return ".".join(word.lower() for word in words) if words else name.lower()


class _Topic:
    """``Model.topic``: works on the class and on an instance."""

    def __get__(self, instance: object, owner: type[DataModel]) -> str:
        return owner.topic_name()


class DataModel(BaseModel):
    """Base class for every message. See the module docstring."""

    version: str
    mRID: str | None = None
    timestamp: datetime | None = None

    #: This class's topic. A subclass may override it with a ``ClassVar[str]``.
    topic: ClassVar[_Topic] = _Topic()

    _sent_at: float | None = PrivateAttr(default=None)

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @classmethod
    def topic_name(cls) -> str:
        """An explicit ``topic`` string on the class or a base, else derived."""
        for klass in cls.__mro__:
            candidate = klass.__dict__.get("topic")
            if isinstance(candidate, str):
                return candidate
            if isinstance(candidate, _Topic):
                break
        return topic_from_name(cls.__name__)


def sent_at(message: DataModel) -> float | None:
    """When a transport's producer sent ``message`` (epoch seconds); ``None``
    for a message that did not cross a transport."""
    return message._sent_at


def stamp_sent_at(message: DataModel, when: float) -> None:
    """Record when ``message`` was sent; transports call it on receipt."""
    message._sent_at = when
