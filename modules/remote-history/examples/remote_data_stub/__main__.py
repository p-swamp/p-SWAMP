# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``python -m remote_data_stub``: serve the history of the source that
``REMOTE_DATA_STUB_SOURCE`` names (``name:entry-point``), on ``REMOTE_DATA_STUB_PORT``."""

from __future__ import annotations

import os
import sys

import uvicorn

from pswamp_core.pipeline_config import PipelineConfigError, resolve_entry
from pswamp_core.sources import SourceModule

from .app import create_app

DEFAULT_SOURCE = "sample:sample-replay"


def main() -> int:
    spec = os.environ.get("REMOTE_DATA_STUB_SOURCE", "").strip() or DEFAULT_SOURCE
    name, _, entry = spec.partition(":")
    if not name or not entry:
        print(f"REMOTE_DATA_STUB_SOURCE: {spec!r} is not name:entry-point", file=sys.stderr)
        return 2
    try:
        cls = resolve_entry(entry)
    except PipelineConfigError as error:
        print(f"REMOTE_DATA_STUB_SOURCE: {error}", file=sys.stderr)
        return 2
    if not (issubclass(cls, SourceModule) and cls.kind == "history"):
        print(f"REMOTE_DATA_STUB_SOURCE: {entry!r} is not a history source", file=sys.stderr)
        return 2
    uvicorn.run(create_app(cls.from_env(name)), host="0.0.0.0", port=int(os.environ.get("REMOTE_DATA_STUB_PORT", "8100")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
