# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""What the PMU test streamer's pipeline is made of.

The server builds one run per client from ``PIPELINE``; whoever hosts the
modules hosts them from it too: the server with the in-memory transport, a
worker with Kafka
(``PSWAMP_WORKER_PIPELINES=pswamp_modules.pipelines.pmu_test_streamer:PIPELINE``).
The streamer's web API is ``app/server-python/src/pmu_test_streamer/api.py``.

Its sources come from ``PMU_TEST_STREAMER_DATA_CLIENTS``, by default the
sample recording (the source a run starts on) and the synthetic live feed.
Every frame gets the CIM reference ``PMU_TEST_STREAMER_CIM_REFERENCE``
(``none`` for no reference).
"""

from __future__ import annotations

import os

from pswamp_core.datagateway import CimReferenceEnricher, DataGateway, gateway_from_env
from pswamp_core.pipeline import Pipeline

from ..excursion import ExcursionModule
from ..frame_stats import FrameStatsModule
from ..range_summary import RangeSummaryModule

APP = "pmu-test-streamer"

DATA_CLIENTS_VARIABLE = "PMU_TEST_STREAMER_DATA_CLIENTS"
DEFAULT_DATA_CLIENTS = (
    "sample:pswamp_modules.sources.sample_client:SampleRecordingClient,"
    "live:pswamp_modules.sources.live_client:LiveSyntheticClient"
)

CIM_REFERENCE_VARIABLE = "PMU_TEST_STREAMER_CIM_REFERENCE"
DEFAULT_CIM_REFERENCE = "n44-cim-stub"


def gateway() -> DataGateway:
    reference = os.environ.get(CIM_REFERENCE_VARIABLE, "").strip() or DEFAULT_CIM_REFERENCE
    cim = CimReferenceEnricher(None if reference == "none" else reference)
    return gateway_from_env(DATA_CLIENTS_VARIABLE, DEFAULT_DATA_CLIENTS, enrichers=[cim])


#: Frames → frame stats → excursion, plus a range summary answering commands.
PIPELINE = Pipeline(APP, gateway, modules=(FrameStatsModule, ExcursionModule, RangeSummaryModule))
