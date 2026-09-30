# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The errors app: one socket per browser carrying the operational errors of
any of its pipeline runs, for the layout's error tray.

It owns no pipeline. Each app over a core pipeline forwards its error topic
into ``HUB`` (``shared.serve_pipeline``), addressed to the clients whose run it
was, and ``HUB`` pushes each notice down that client's tray socket, on
whatever page they are looking at.

  router      /api/errors/ws, downstream only
  WS_MESSAGE  ErrorNotice
"""

from .api import router
from .hub import HUB, ErrorHub, ErrorNotice

WS_MESSAGE = ErrorNotice

__all__ = ["HUB", "WS_MESSAGE", "ErrorHub", "ErrorNotice", "router"]
