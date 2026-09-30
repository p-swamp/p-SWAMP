# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Every timestamp in the core is UTC-aware; these make it so."""

from datetime import datetime, timezone

__all__ = ["UTC", "ensure_utc", "utcnow"]

UTC = timezone.utc


def ensure_utc(moment: datetime) -> datetime:
    """``moment`` as a UTC-aware datetime. Naive input is taken as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def utcnow() -> datetime:
    """The current instant, UTC-aware."""
    return datetime.now(UTC)
