# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""A dummy remote data service: any history ``SourceModule``'s records, served over
the remote data contract (doc/remote-data-integration-contract.md).

It stands where a deployment's own service, in front of its own store, would
stand. It reuses the core for brevity; a real service only has to follow the
contract, in any language.

    python -m remote_data_stub      # modules/remote-history/examples on PYTHONPATH

    REMOTE_DATA_STUB_SOURCE=sample:sample-replay     # name:entry-point; SAMPLE_PATH etc. apply
    REMOTE_DATA_STUB_PORT=8100
"""

from .app import create_app

__all__ = ["create_app"]
