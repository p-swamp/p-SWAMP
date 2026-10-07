# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""A worker: a process that hosts pipelines' modules.

    python -m pswamp_core.worker

with the transport the server uses, and the pipeline files whose modules to
host::

    PSWAMP_TRANSPORT=kafka:pswamp_core.transport.kafka:KafkaTransport
    KAFKA_BOOTSTRAP_SERVERS=kafka:9092
    PSWAMP_WORKER_PIPELINES=pmu-test-streamer.toml   # pipeline files, comma-separated
    PSWAMP_WORKER_MODULES=range-summary              # optional: only these modules

A pipeline file is a path, relative to the working directory or absolute. In
the image the workers run from the pipelines folder (``/workspace/p-SWAMP/pipelines``,
the repo's ``pipelines/``), so each entry is a bare ``<app>.toml``. Its modules
are found through the ``pswamp.modules`` entry points, so any working
directory works for them (every module project is installed).

One worker may host every module, or a heavy module gets a worker (and a CPU
limit) of its own. A module that reads the sources gets a set built from the
same ``<APP>_SOURCES`` the server reads, so those go to its worker too.

Exits 2, saying why, when the transport is in-memory (the server hosts the
modules itself then), a pipeline file is unusable, or no module is named.
Stops on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

from .host import serve_hosts
from .log import get_logger
from .pipeline import Pipeline
from .pipeline_config import load_pipeline
from .transport import TRANSPORT_VARIABLE, transport_from_env

__all__ = ["MODULES_VARIABLE", "PIPELINES_VARIABLE", "load_pipelines", "main"]

logger = get_logger("pswamp_core.worker")

#: Comma-separated pipeline files (``<app>.toml``), relative to the working directory or absolute.
PIPELINES_VARIABLE = "PSWAMP_WORKER_PIPELINES"
#: Optional comma-separated module names: host only these.
MODULES_VARIABLE = "PSWAMP_WORKER_MODULES"


def load_pipelines(spec: str) -> list[Pipeline]:
    """The pipelines in the files ``spec`` names. Raises ``ValueError``
    (``PipelineConfigError``) saying which file and why."""
    pipelines = []
    for path in (part.strip() for part in spec.split(",")):
        if not path:
            continue
        if not path.endswith(".toml"):
            raise ValueError(
                f"{PIPELINES_VARIABLE}: {path!r} is not a pipeline file; name <app>.toml files "
                "(the module.path:PIPELINE form is gone with the Python pipelines)"
            )
        pipelines.append(load_pipeline(path))
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
    try:
        pipelines = load_pipelines(os.environ.get(PIPELINES_VARIABLE, ""))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    hosts = [host for pipeline in pipelines for host in pipeline.hosts(transport, only=only)]
    if not hosts:
        print(f"{PIPELINES_VARIABLE} (and {MODULES_VARIABLE}) name no module to host, e.g.", file=sys.stderr)
        print(f"  {PIPELINES_VARIABLE}=pipelines/pmu-test-streamer.toml", file=sys.stderr)
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
