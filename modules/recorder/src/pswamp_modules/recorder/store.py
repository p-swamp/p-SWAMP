"""The recordings on disk: DuckDB files, one per segment, in one folder.

A connection is opened per call and closed again, so a reader never meets a
writer's open file, in this process or another.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
from pswamp_models.common import DataModel
from pswamp_models.pmu import PmuFrame

from . import codecs
from .codecs import Codec, Entry, FrameCodec

__all__ = ["Store"]

logger = logging.getLogger(__name__)


def _size(path: Path) -> int:
    """A segment's bytes on disk, its write-ahead log included; 0 when it is gone."""
    total = 0
    for each in (path, path.with_name(path.name + ".wal")):
        try:
            total += each.stat().st_size
        except FileNotFoundError:
            pass
    return total


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


class Store:
    """Messages buffered by ``append``, written by ``flush`` through their class's codec, read back by ``read``."""

    def __init__(
        self,
        folder: Path,
        *,
        roll: timedelta = timedelta(hours=6),
        flush_every: timedelta = timedelta(seconds=1),
        max_bytes: int = 5 * 1024**3,
        max_buffer: int = 100_000,
        codecs: Sequence[Codec] = (FrameCodec(),),
    ) -> None:
        self.folder = folder
        #: What may be appended, by message class.
        self.codecs: dict[type[DataModel], Codec] = {codec.model: codec for codec in codecs}
        self.roll = roll
        self.max_bytes = max_bytes
        self.flush_every = flush_every
        #: Frames kept in memory while the disk refuses them; past it the oldest are dropped.
        self.max_buffer = max_buffer
        self._failing = False
        #: Held by whatever touches the buffer or the open segment: the run's worker thread appends
        #: (``process``) while another flushes a quiet feed, and a reader flushes before it reads.
        self._lock = threading.RLock()
        self._buffer: list[Entry] = []
        self._segment: Path | None = None
        #: What the segment being written holds one of, per codec (its ``segment_key``), and its first instant.
        self._keys: dict[str, str] = {}
        self._start: datetime | None = None
        self._flushed = time.monotonic()

    def _codec(self, message: DataModel) -> Codec:
        try:
            return self.codecs[type(message)]
        except KeyError:
            raise TypeError(f"recorder {self.folder}: no codec for {type(message).__name__}") from None

    def append(self, message: DataModel) -> None:
        """Buffer ``message``; one whose segment key differs, or a segment as old as ``roll`` (by message
        time), starts a new segment."""
        codec = self._codec(message)
        arrived = datetime.now(UTC)
        key, moment = codec.segment_key(message), codec.time(message) or arrived
        with self._lock:
            if self._start is not None and (self._keys.get(codec.table, key) != key or moment - self._start >= self.roll):
                self.roll_over()
            if self._start is None:
                self._start = moment
            self._keys.setdefault(codec.table, key)
            self._buffer.append(Entry(message, moment, arrived))
            if len(self._buffer) > self.max_buffer:
                dropped = len(self._buffer) - self.max_buffer
                del self._buffer[:dropped]
                logger.error("recorder %s: the disk is not taking frames; dropped the %d oldest buffered", self.folder, dropped)
            if time.monotonic() - self._flushed >= self.flush_every.total_seconds():
                self.flush()

    def roll_over(self) -> None:
        """Write what is buffered; the next frame opens a new segment."""
        with self._lock:
            self.flush()
            if self._buffer:
                # The write failed: these belong to the segment that is closing, and must not open the next one.
                logger.error("recorder %s: dropped %d frames that could not be written", self.folder, len(self._buffer))
                self._buffer.clear()
            self._segment = self._start = None
            self._keys = {}

    def flush(self) -> None:
        """Write what is buffered. A write the disk refuses is logged and retried at the next flush."""
        with self._lock:
            self._flushed = time.monotonic()
            if not self._buffer:
                return
            try:
                self._write()
            except (duckdb.Error, OSError):
                if not self._failing:
                    logger.exception("recorder %s: cannot write %d buffered frames; will retry", self.folder, len(self._buffer))
                self._failing = True
                return
            self._failing = False
            self._buffer.clear()
            self._sweep()

    def _write(self) -> None:
        if self._segment is None:
            self.folder.mkdir(parents=True, exist_ok=True)
            self._segment = self._free_segment(self._buffer[0].ts)
        groups: dict[Codec, list[Entry]] = {}
        for entry in self._buffer:
            groups.setdefault(self._codec(entry.message), []).append(entry)
        con = duckdb.connect(str(self._segment))
        try:
            for codec in groups:
                codec.ensure(con)
            con.execute("BEGIN")  # all or nothing, so a retry after a failure cannot write a message twice
            for codec, entries in groups.items():
                codec.write(con, entries)
            con.execute("COMMIT")  # plain SQL: test_tools_layering keeps the call syntax for the CIM graph's writer
        finally:
            con.close()

    def _free_segment(self, first: datetime) -> Path:
        """A segment is always a new file: a stream that starts again at the same instant must not append to the old one."""
        name = f"{codecs.naive(first):%Y%m%dT%H%M%S.%f}"
        path, n = self.folder / f"{name}.duckdb", 0
        while path.exists():
            n += 1
            path = self.folder / f"{name}_{n}.duckdb"  # '_' sorts after '.', so a name still orders by when it was made
        return path

    def _sweep(self) -> None:
        """Delete the oldest segments (by when they were written) while the folder is over ``max_bytes``; never the open one."""
        segments = self.segments()
        total = sum(_size(path) for path in segments)
        for path in sorted((p for p in segments if p != self._segment), key=lambda p: (_mtime(p), p.name)):
            if total <= self.max_bytes:
                return
            size = _size(path)
            try:
                path.unlink(missing_ok=True)
                path.with_name(path.name + ".wal").unlink(missing_ok=True)
            except OSError:  # a reader has it open (Windows): leave it for the next sweep
                continue
            total -= size

    def segments(self) -> list[Path]:
        return sorted(self.folder.glob("*.duckdb"))

    def _open(self, segment: Path) -> duckdb.DuckDBPyConnection | None:
        """A connection to ``segment``, or ``None`` when it is gone (swept) or unreadable (logged, skipped)."""
        try:
            return duckdb.connect(str(segment))
        except (duckdb.Error, OSError):
            if segment.exists():
                logger.exception("recorder %s: cannot open segment %s", self.folder, segment.name)
            return None

    def read(self, start: datetime | None = None, end: datetime | None = None) -> Iterator[PmuFrame]:
        """The frames with ``start <= timestamp < end``, segment by segment (see the README on their order)."""
        self.flush()
        codec = self.codecs.get(PmuFrame)
        if codec is None:
            return
        for segment in self.segments():
            con = self._open(segment)
            if con is None:
                continue
            try:
                yield from codec.read(con, start, end)
            finally:
                con.close()

    def bounds(self) -> tuple[datetime, datetime] | None:
        """The first and last instants of frames held, or ``None``."""
        codec = self.codecs.get(PmuFrame)
        first = last = None
        for segment in self.segments() if codec else ():
            con = self._open(segment)
            if con is None:
                continue
            try:
                found = codec.bounds(con)
            finally:
                con.close()
            if found is not None:
                low, high = found
                first = low if first is None else min(first, low)
                last = high if last is None else max(last, high)
        return None if first is None else (first, last)
