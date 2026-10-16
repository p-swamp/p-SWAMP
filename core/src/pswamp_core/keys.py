# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``StreamKey``: what a record's transport key says about its run.

    42                    a run key alone: a client id, or live.<source>
    42#1760512345678.3    run 42, its run id 1760512345678, its stream 3

- **run**: what the run is isolated by. A subscription to ``42`` hears every
  key of that run, ``42#…`` included (``TransportSubscription.wants``).
- **run id**: one per ``PipelineRun``, and increasing, so a module host can
  tell a new run of the same client (after a server restart, say) from the
  one it holds, and a late message of an older run from either.
- **stream**: counts the times the run's stream started over (a seek, a
  switch, a loop to the start). A module host resets its instance when it
  goes up, in order with the frames, since it rides on them.

A key without ``#`` parses as run id 0, stream 0: what a test or a script
publishing by hand uses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

__all__ = ["StreamKey", "next_run_id", "run_of"]

_SEPARATOR = "#"


@dataclass(frozen=True)
class StreamKey:
    run: str
    run_id: int = 0
    stream: int = 0

    @classmethod
    def parse(cls, key: str) -> StreamKey:
        run, separator, generation = key.partition(_SEPARATOR)
        if not separator:
            return cls(run)
        run_id, _, stream = generation.partition(".")
        try:
            return cls(run, int(run_id), int(stream or 0))
        except ValueError:
            return cls(key)  # not one of ours: an opaque run key

    def at(self, stream: int) -> StreamKey:
        return replace(self, stream=stream)

    def __str__(self) -> str:
        if self.run_id == 0 and self.stream == 0:
            return self.run
        return f"{self.run}{_SEPARATOR}{self.run_id}.{self.stream}"


def run_of(key: str) -> str:
    """The run a transport key belongs to."""
    return key.partition(_SEPARATOR)[0]


_last_run_id = 0


def next_run_id() -> int:
    """A new run id: milliseconds since the epoch, past the last one given.

    Ordered across processes because only the server builds runs, and it runs
    as one replica. If the clock steps back across a server restart, a module
    host takes the new run's messages for an older run's, and drops them,
    until the clock passes the old run id.
    """
    global _last_run_id
    _last_run_id = max(time.time_ns() // 1_000_000, _last_run_id + 1)
    return _last_run_id
