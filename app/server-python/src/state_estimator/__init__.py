"""The State Estimator app's web API, and the page that shows its module's results.
The module is ``pswamp_modules.state_estimator``; its pipeline is
``pipelines/state-estimator.toml`` at the repo root.

  router      the endpoints, mounted under /api/state-estimator
  lifespan    the shared live run, the module hosted here when there is no broker
  WS_MESSAGE  the model pushed down the socket
"""

from .api import StateEstimatorState, lifespan, router

WS_MESSAGE = StateEstimatorState

__all__ = ["WS_MESSAGE", "StateEstimatorState", "lifespan", "router"]
