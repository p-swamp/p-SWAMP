# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``recordable_models()``: the messages a recorder may keep, found from the classes themselves.

A producer opts its message in with ``recordable = True`` on the class; nothing is listed here, so
a new message is recordable the moment its class says so, and a recorder or a document asks this
one place. The choice of which of them a deployment records is configuration, not this.
"""

from __future__ import annotations

import importlib
import pkgutil

from .data_model import DataModel

__all__ = ["recordable_models"]


def _subclasses(base: type[DataModel]) -> list[type[DataModel]]:
    found: list[type[DataModel]] = []
    for each in base.__subclasses__():
        found.append(each)
        found.extend(_subclasses(each))
    return found


def _concrete(model: type[DataModel]) -> bool:
    """Not a generic base (``ResultEnvelope`` itself) nor one of its parametrisations
    (``ResultEnvelope[FrameStats]``): a message is the named subclass."""
    meta = model.__pydantic_generic_metadata__
    return not meta["parameters"] and meta["origin"] is None


def recordable_models() -> dict[str, type[DataModel]]:
    """Every recordable message class of ``pswamp_models``, by topic.

    Imports every package of ``pswamp_models`` first, since a class exists only once imported. A
    message lives here and nowhere else, so a class defined elsewhere (a test's stand-in) is not listed.
    """
    import pswamp_models

    for found in pkgutil.walk_packages(pswamp_models.__path__, "pswamp_models."):
        importlib.import_module(found.name)
    models: dict[str, type[DataModel]] = {}
    for model in _subclasses(DataModel):
        if model.recordable and _concrete(model) and model.__module__.startswith("pswamp_models."):
            topic = model.topic_name()
            if models.setdefault(topic, model) is not model:
                raise ValueError(f"two recordable messages share the topic {topic!r}: {models[topic]!r} and {model!r}")
    return dict(sorted(models.items()))
