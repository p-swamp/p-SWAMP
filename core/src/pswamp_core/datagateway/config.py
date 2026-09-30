# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""A run's data clients, named by the environment.

Each app reads its own variable, ``<APP>_DATA_CLIENTS``, a comma-separated
list of ``name:module.path:Class`` specs, falling back to a default in code::

    PMU_TEST_STREAMER_DATA_CLIENTS=sample:pmu_test_streamer.sample_client:SampleRecordingClient,live:acme.pmu:KafkaFeed
    LIVE_BOOTSTRAP_SERVERS=kafka.acme:9092

Each client is built with ``from_env(name)``, so it reads its own
``{NAME}_{SETTING}`` block. A deployment plugs in its own provider with one
package in the image and one variable, and no change to this repo.
"""

from __future__ import annotations

import os

from ..settings import MissingSettingError, load_class, parse_specs
from .data_client import DataClient
from .data_gateway import DataGateway

__all__ = ["clients_from_env", "gateway_from_env"]


def clients_from_env(variable: str, default: str) -> list[DataClient]:
    """The clients ``variable`` names, or ``default`` when it is unset, each
    built from its own environment block."""
    spec = os.environ.get(variable, "").strip() or default
    if not spec:
        raise MissingSettingError(f"{variable} is unset and there is no default")
    return [
        load_class(variable, module_path, class_name, DataClient).from_env(name)
        for name, module_path, class_name in parse_specs(variable, spec)
    ]


def gateway_from_env(variable: str, default: str) -> DataGateway:
    """A ``DataGateway`` over ``clients_from_env(variable, default)``."""
    return DataGateway(clients_from_env(variable, default))
