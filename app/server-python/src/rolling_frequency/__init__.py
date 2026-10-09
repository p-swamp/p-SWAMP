"""The Rolling frequency app's web API, and the page that shows its module's results.
The module is ``pswamp_modules.rolling_frequency``; its pipeline is
``pswamp_modules.pipelines.rolling_frequency``.

  router      the endpoints, mounted under /api/rolling-frequency
  lifespan    the results cache, and the module hosted here when there is no broker
  WS_MESSAGE  the model pushed down the socket
"""

from .api import RollingFrequencyState, lifespan, router

WS_MESSAGE = RollingFrequencyState

__all__ = ["WS_MESSAGE", "RollingFrequencyState", "lifespan", "router"]
