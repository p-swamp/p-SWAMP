# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Every timestamp in a message is UTC-aware; this makes it so.

The one definition: ``pswamp_core.util.time`` re-exports it, so the core and
the models normalise timestamps the same way.
"""

from datetime import datetime, timezone

__all__ = ["UTC", "ensure_utc"]

UTC = timezone.utc


def ensure_utc(moment: datetime) -> datetime:
    """``moment`` as a UTC-aware datetime. Naive input is taken as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
