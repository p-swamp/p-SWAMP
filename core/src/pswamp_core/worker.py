# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""A worker: a process that hosts pipelines' modules.

    python -m pswamp_core.worker

run from anywhere the pipelines import (``pswamp_modules`` is installed, so
any working directory), with the transport the server uses::

    PSWAMP_TRANSPORT=kafka:pswamp_core.transport.kafka:KafkaTransport
    KAFKA_BOOTSTRAP_SERVERS=kafka:9092
    PSWAMP_WORKER_PIPELINES=pswamp_modules.pipelines.pmu_test_streamer:PIPELINE
    PSWAMP_WORKER_MODULES=range-summary        # optional: only these modules

One worker may host every module, or a heavy module gets a worker (and a CPU
limit) of its own. A module that reads the gateway gets one built from the
same ``<APP>_DATA_CLIENTS`` the server reads, so those go to its worker too.

Exits 2, saying why, when the transport is in-memory (the server hosts the
modules itself then) or no pipeline is named. Stops on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import signal
import sys

from .host import serve_hosts
from .log import get_logger
from .pipeline import Pipeline
from .transport import TRANSPORT_VARIABLE, transport_from_env

__all__ = ["MODULES_VARIABLE", "PIPELINES_VARIABLE", "load_pipelines", "main"]

logger = get_logger("pswamp_core.worker")

#: Comma-separated ``module.path:NAME`` references to ``Pipeline`` objects.
PIPELINES_VARIABLE = "PSWAMP_WORKER_PIPELINES"
#: Optional comma-separated module names: host only these.
MODULES_VARIABLE = "PSWAMP_WORKER_MODULES"


def load_pipelines(spec: str) -> list[Pipeline]:
    """The pipelines ``spec`` names, imported."""
    pipelines = []
    for reference in (part.strip() for part in spec.split(",")):
        if not reference:
            continue
        module_path, _, name = reference.partition(":")
        if not module_path or not name:
            raise ValueError(f"{PIPELINES_VARIABLE}: {reference!r} is not module.path:NAME")
        pipeline = getattr(importlib.import_module(module_path), name, None)
        if not isinstance(pipeline, Pipeline):
            raise ValueError(f"{PIPELINES_VARIABLE}: {reference} is not a Pipeline")
        pipelines.append(pipeline)
    return pipelines


def _names(spec: str) -> set[str] | None:
    names = {part.strip() for part in spec.split(",") if part.strip()}
    return names or None


def main() -> int:
    """Host the named modules until SIGINT/SIGTERM; the exit code."""
    transport = transport_from_env()
    if transport.in_process:
        print(f"{TRANSPORT_VARIABLE} is unset, so the server hosts the modules itself. A worker needs a broker:", file=sys.stderr)
        print(f"  {TRANSPORT_VARIABLE}=kafka:pswamp_core.transport.kafka:KafkaTransport  (and KAFKA_BOOTSTRAP_SERVERS)", file=sys.stderr)
        return 2
    only = _names(os.environ.get(MODULES_VARIABLE, ""))
    pipelines = load_pipelines(os.environ.get(PIPELINES_VARIABLE, ""))
    hosts = [host for pipeline in pipelines for host in pipeline.hosts(transport, only=only)]
    if not hosts:
        print(f"{PIPELINES_VARIABLE} (and {MODULES_VARIABLE}) name no module to host, e.g.", file=sys.stderr)
        print(f"  {PIPELINES_VARIABLE}=pswamp_modules.pipelines.pmu_test_streamer:PIPELINE", file=sys.stderr)
        return 2

    async def run() -> None:
        task = asyncio.create_task(serve_hosts(hosts))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, task.cancel)
        logger.info("worker hosting %s", ", ".join(f"{h.app}/{h.name}" for h in hosts))
        try:
            await asyncio.wait([task])  # until a signal cancels it; a crash still raises below
            if not task.cancelled():
                task.result()
        finally:
            await transport.close()
        logger.info("worker stopped")

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
