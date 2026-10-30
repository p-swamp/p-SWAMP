# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Where the CIM graph is, and what it is loaded from.

One store for the whole deployment, ``PSWAMP_CIM_URL`` (an Oxigraph server: SPARQL
queries at ``<url>/query``, updates at ``<url>/update``). Unset, each process has an
in-process store of its own (tests, scripts, a server alone). A script may name any
other LazyCIM store instead (``backend``), or hand a module a repository outright.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["CimSettings"]


@dataclass(frozen=True)
class CimSettings:
    """Hashable: it keys a process's in-process stores.

    Where the graph is, first match wins: ``backend``, a store someone else filled; ``url``, the
    deployment's Oxigraph; neither, an in-process store filled with ``cim_path``. A script that
    already holds a LazyCIM repository needs no settings at all: it hands the repository to the
    module (``module.cim_repo = repo``)."""

    #: The Oxigraph server, ``http://host:7878``; an in-process store when unset.
    url: str | None = None
    #: A folder of CGMES ``*_<PROFILE>.xml`` files; Nordic44 (downloaded by LazyCIM) when unset.
    cim_path: Path | None = None
    #: Any LazyCIM SPARQL backend, as a callable that makes one (``functools.partial(GraphDBBackend,
    #: url, repository="n44")``): it must pickle, since a child process makes its own. The store
    #: it opens is filled already; p-SWAMP reads it, and never fills, resets or stamps it.
    backend: Callable[[], Any] | None = None
    #: Whether another process reaches the same data through ``backend`` (a server, a file on
    #: disk), so a reader may follow it from a process of its own. An in-memory store is not.
    shared: bool = False

    @classmethod
    def from_env(cls) -> CimSettings:
        """``PSWAMP_CIM_URL``, ``PSWAMP_CIM_PATH``."""
        path = os.environ.get("PSWAMP_CIM_PATH", "").strip()
        url = os.environ.get("PSWAMP_CIM_URL", "").strip().rstrip("/") or None
        return cls(url, Path(path) if path else None)
