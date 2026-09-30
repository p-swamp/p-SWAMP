# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Stopping tasks without swallowing the caller's own cancellation.

The usual ``task.cancel()`` then ``with suppress(CancelledError): await task``
also swallows a cancellation of the *caller* that arrives meanwhile, so the
caller carries on as if never cancelled. These two hold that cancellation until
the work is done, then re-raise it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

__all__ = ["cancel_and_wait", "finish"]

T = TypeVar("T")


async def finish(awaitable: Awaitable[T]) -> T:
    """Run ``awaitable`` to its end even if the caller is cancelled meanwhile;
    then re-raise that cancellation, or return the result."""
    task = asyncio.ensure_future(awaitable)
    interrupted = False
    while not task.done():
        try:
            await asyncio.wait([task])
        except asyncio.CancelledError:
            interrupted = True
    if interrupted:
        if not task.cancelled():
            task.exception()  # retrieved; the cancellation wins
        raise asyncio.CancelledError
    return task.result()


async def cancel_and_wait(*tasks: asyncio.Task, ignore: tuple[type[BaseException], ...] = ()) -> None:
    """Cancel ``tasks`` and wait until all have finished.

    Re-raises an exception a task ended with, other than its cancellation and
    anything in ``ignore``.
    """
    for task in tasks:
        task.cancel()
    try:
        if tasks:
            await finish(asyncio.wait(tasks))
    finally:
        errors = [task.exception() for task in tasks if task.done() and not task.cancelled()]
    for error in errors:
        if error is not None and not isinstance(error, ignore):
            raise error
