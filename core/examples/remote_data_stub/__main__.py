# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``python -m remote_data_stub``: serve the history of the client that
``REMOTE_DATA_STUB_CLIENT`` names, on ``REMOTE_DATA_STUB_PORT``."""

from __future__ import annotations

import os

import uvicorn

from pswamp_core.datagateway import clients_from_env

from .app import create_app

DEFAULT_CLIENT = "sample:pmu_test_streamer.sample_client:SampleRecordingClient"


def main() -> int:
    (client,) = clients_from_env("REMOTE_DATA_STUB_CLIENT", DEFAULT_CLIENT)
    uvicorn.run(create_app(client), host="0.0.0.0", port=int(os.environ.get("REMOTE_DATA_STUB_PORT", "8100")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
