# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Standard-library logging to stdout, which Docker and k8s capture.

A bare ``logging.getLogger`` has no handler, and uvicorn configures only its
own loggers, so each core logger gets one handler of its own and does not
propagate. Idempotent, so a reload cannot stack handlers.
"""

import logging
import sys

__all__ = ["get_logger"]


def get_logger(name: str) -> logging.Logger:
    """A stdout logger for ``name``; safe to call repeatedly."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(f"%(asctime)s %(levelname)s [{name}] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
