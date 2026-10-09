"""What the Rolling frequency pipeline is made of: the ``rolling-frequency.*`` topics, the
configured sources, and the module. A worker hosts the module with
``PSWAMP_WORKER_PIPELINES=pswamp_modules.pipelines.rolling_frequency:PIPELINE``.

By default the only source is the 30 s line-trip recording, replayed per
client: long enough for the module's five-second window, and a recording, so
its results can be kept and shown again.
"""

from pswamp_core.datagateway import DataGateway, gateway_from_env
from pswamp_core.pipeline import Pipeline

from ..rolling_frequency import RollingFrequencyModule

APP = "rolling-frequency"

DATA_CLIENTS_VARIABLE = "ROLLING_FREQUENCY_DATA_CLIENTS"
DEFAULT_DATA_CLIENTS = "line-trip:pswamp_modules.sources.sample_client:LineTripRecordingClient"


def gateway() -> DataGateway:
    return gateway_from_env(DATA_CLIENTS_VARIABLE, DEFAULT_DATA_CLIENTS)


PIPELINE = Pipeline(APP, gateway, modules=(RollingFrequencyModule,))
