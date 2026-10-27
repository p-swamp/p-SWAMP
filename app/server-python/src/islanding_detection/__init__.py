"""The Islanding detection app's web API, and the page that shows its module's results.
The module is ``pswamp_modules.islanding_detection``; its pipeline is
``pipelines/islanding-detection.toml`` at the repo root.

  router      the endpoints, mounted under /api/islanding-detection
  lifespan    the shared live run, the module hosted here when there is no broker
  WS_MESSAGE  the model pushed down the socket
"""

from .api import IslandingDetectionState, lifespan, router

WS_MESSAGE = IslandingDetectionState

__all__ = ["WS_MESSAGE", "IslandingDetectionState", "lifespan", "router"]
