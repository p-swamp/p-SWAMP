"""The CIM graph app: the grid on its geographic layout, its breakers operated by editing the graph,
of which this app is the only writer.

Same public surface as every app package — src/server.py uses nothing else:

  router      the endpoints, mounted under /api/cim-graph
  WS_MESSAGE  the model this app pushes down its socket
  lifespan    loads the grid into the store, in the background, as the server starts

Note the spelling difference: this directory has to be a Python identifier,
while its URL prefix is hyphenated to match the web client's route —
`cim_graph` vs `/api/cim-graph`.
"""

from .api import lifespan, router
from .model import CimGraphState

WS_MESSAGE = CimGraphState

__all__ = ["WS_MESSAGE", "CimGraphState", "lifespan", "router"]
