# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Editing the CIM graph from a test or a script, where no web backend runs to do it.

In a deployment the web backend is the graph's only writer. A test of a module that follows the
graph, or a script trying one out, has none, and edits the process's own store with ``edit``, as the
web backend would: one commit, one update. Never use it against a shared store.
"""

from __future__ import annotations

from typing import Any

from lazycim import CIMRepository
from lazycim.demo import CIM100

from .grid import NAMESPACE_ALIASES
from .settings import CimSettings
from .store import open_store

__all__ = ["edit", "reset"]


def edit(settings: CimSettings, mrid: str, **values: Any) -> None:
    """Set ``values`` (``open=True``, ``p=120.0``) on the object ``mrid`` of the process's store, and commit."""
    store = open_store(settings)
    repo = CIMRepository(store.writer_backend(), default_namespace=CIM100, graphs=store.layout, namespace_aliases=NAMESPACE_ALIASES)
    target = repo.from_mRID(mrid)
    for name, value in values.items():
        setattr(target, name, value)
    repo.commit()


def reset(settings: CimSettings) -> None:
    """Put the process's store back as it was loaded (its SSH profile)."""
    open_store(settings).reset()
