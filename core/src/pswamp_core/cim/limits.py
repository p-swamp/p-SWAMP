# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Each equipment end's permanent current limit, from the graph's ``CurrentLimit``s.

A terminal's limits hang off its ``OperationalLimitSet``s; the one that holds for ever is the one with
no acceptable duration, else the longest-lasting (LazyCIM's ``permanent_limit``, the rule the
simulation's protection uses, so a page's loading and the protection agree). LazyCIM reads the same
table for ``LiveTops.limit``, privately; until it offers the reading too, it is here.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from lazycim import F, L
from lazycim.sim.tops_live import permanent_limit
from lazycim.sim.topology import terminal_table

if TYPE_CHECKING:
    from lazycim import CIMRepository

__all__ = ["current_limits"]


def current_limits(repo: CIMRepository) -> dict[tuple[str, int], float]:
    """Each equipment end's permanent current limit, ``{(equipment mRID, end): amperes}``; an end with
    none is left out. Two queries."""
    terminals = terminal_table(repo)
    ends = dict(zip(terminals["terminal"], zip(terminals["equipment"], terminals["sequence"], strict=True), strict=True))
    table = repo.query(L.CurrentLimit).to_dataframe(
        value=F.value,
        terminal=F.OperationalLimitSet.Terminal.mRID,
        duration=F.OperationalLimitType.acceptableDuration,
    )
    found: dict[tuple[str, int], list[tuple[float, float | None]]] = {}
    for terminal, amps, duration in zip(table.get("terminal", ()), table.get("value", ()), table.get("duration", ()), strict=True):
        # A limit with no terminal or no type has an empty list in its cell, one with no duration None or NaN.
        if not isinstance(terminal, str) or terminal not in ends or not isinstance(amps, int | float):
            continue
        seconds = float(duration) if isinstance(duration, int | float) and not math.isnan(duration) else None
        equipment, end = ends[terminal]
        found.setdefault((equipment, int(end)), []).append((float(amps), seconds))
    return {end: amps for end, limits in found.items() if (amps := permanent_limit(limits)) is not None}
