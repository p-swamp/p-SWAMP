# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Where the CIM graph is, and what it is loaded from.

One store for the whole deployment, ``PSWAMP_CIM_URL`` (an Oxigraph server: SPARQL
queries at ``<url>/query``, updates at ``<url>/update``). Unset, each process has an
in-process store of its own (tests, scripts, a server alone).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["CimSettings"]


@dataclass(frozen=True)
class CimSettings:
    """Hashable: it keys a process's in-process stores."""

    #: The Oxigraph server, ``http://host:7878``; an in-process store when unset.
    url: str | None = None
    #: A folder of CGMES ``*_<PROFILE>.xml`` files; Nordic44 (downloaded by LazyCIM) when unset.
    cim_path: Path | None = None

    @classmethod
    def from_env(cls) -> CimSettings:
        """``PSWAMP_CIM_URL``, ``PSWAMP_CIM_PATH``."""
        path = os.environ.get("PSWAMP_CIM_PATH", "").strip()
        url = os.environ.get("PSWAMP_CIM_URL", "").strip().rstrip("/") or None
        return cls(url, Path(path) if path else None)
