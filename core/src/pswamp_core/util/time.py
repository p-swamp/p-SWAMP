# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Every timestamp in the core is UTC-aware; these make it so.

``UTC`` and ``ensure_utc`` are the models' own (``pswamp_models.common.utc``),
so a message and the core normalise a timestamp the same way.
"""

from datetime import datetime

from pswamp_models.common.utc import UTC, ensure_utc

__all__ = ["UTC", "ensure_utc", "utcnow"]


def utcnow() -> datetime:
    """The current instant, UTC-aware."""
    return datetime.now(UTC)
