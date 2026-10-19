# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The bases every message builds on, and the pipeline's own messages.

- ``DataModel``: the base of every message (version, topic, UTC timestamp).
- ``Command``: the base of every upstream action.
- ``ResultEnvelope`` and ``AppIdentity``: what a module publishes.
- ``ErrorEvent``: something in a pipeline failed.
- ``AlarmEvent`` and ``AppStatus``: a module's alarms, and the status behind them.
- ``PipelineClosed``: a run stopped.
"""

from .alarms import AlarmEvent, AppStatus
from .command import Command
from .control import ModuleStarted, PipelineClosed
from .data_model import DataModel, sent_at, stamp_sent_at, topic_from_name
from .errors import ErrorEvent
from .results import AppIdentity, ResultEnvelope

__all__ = [
    "AlarmEvent",
    "AppStatus",
    "AppIdentity",
    "Command",
    "DataModel",
    "ErrorEvent",
    "ModuleStarted",
    "PipelineClosed",
    "ResultEnvelope",
    "sent_at",
    "stamp_sent_at",
    "topic_from_name",
]
