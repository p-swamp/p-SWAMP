# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Where data enters a pipeline: the provider contract (``DataClient``) and
the ``DataGateway`` that holds a run's providers as named sources."""

from .config import clients_from_env, gateway_from_env
from .data_client import DataClient
from .data_gateway import DataGateway
from .stream import DataStream
from .time_range import TimeRange

__all__ = ["DataClient", "DataGateway", "DataStream", "TimeRange", "clients_from_env", "gateway_from_env"]
