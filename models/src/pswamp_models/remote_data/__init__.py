# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The remote data contract's two shapes (doc/remote-data-integration-contract.md)."""

from .messages import (
    RemoteDataQuery,
    RemoteDataResult,
    ApiModel,
    RecordResponse,
    RecordMessage,
    Phasor,
    EndResponse,
    EndMessage,
    ErrorResponse,
    ErrorMessage,
    RESULT_ADAPTER,
)

__all__ = [
    "RemoteDataQuery",
    "RemoteDataResult",
    "ApiModel",
    "RecordResponse",
    "RecordMessage",
    "Phasor",
    "EndResponse",
    "EndMessage",
    "ErrorResponse",
    "ErrorMessage",
    "RESULT_ADAPTER"
]
