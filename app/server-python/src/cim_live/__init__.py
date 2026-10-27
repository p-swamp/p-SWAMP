"""The live grid feed: every frame of the RT sim, read back off the transport, as the page plots it.

Same public surface as every app package — src/server.py uses nothing else:

  router      the socket, mounted under /api/cim-live
  WS_MESSAGE  the model this app pushes down its socket
"""

from .api import router
from .model import LiveFeed

WS_MESSAGE = LiveFeed

__all__ = ["WS_MESSAGE", "LiveFeed", "router"]
