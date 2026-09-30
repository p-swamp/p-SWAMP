# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""What the PMU test streamer's pipeline is made of.

Its sources come from ``PMU_TEST_STREAMER_DATA_CLIENTS``, by default the
sample recording (the source a run starts on) and the synthetic live feed.
"""

from __future__ import annotations

from pswamp_core.datagateway import DataGateway, gateway_from_env

APP = "pmu-test-streamer"

DATA_CLIENTS_VARIABLE = "PMU_TEST_STREAMER_DATA_CLIENTS"
DEFAULT_DATA_CLIENTS = (
    "sample:pmu_test_streamer.sample_client:SampleRecordingClient,"
    "live:pmu_test_streamer.live_client:LiveSyntheticClient"
)


def gateway() -> DataGateway:
    return gateway_from_env(DATA_CLIENTS_VARIABLE, DEFAULT_DATA_CLIENTS)
