from pswamp_web.wire import IslandingState

from .api import router

# The model this app pushes down its socket, collected into the published api
# contract by api_contract.py -- see doc/the-client-server-api.md.
WS_MESSAGE = IslandingState

__all__ = ["WS_MESSAGE", "router"]
