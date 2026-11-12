"""The recordings on disk: DuckDB files, one per segment, in one folder.

A connection is opened per call and closed again, so a reader never meets a
writer's open file, in this process or another.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
from pswamp_models.pmu import PmuFrame, PmuHeader

__all__ = ["Store"]

logger = logging.getLogger(__name__)

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS layouts (id VARCHAR PRIMARY KEY, header VARCHAR)",
    "CREATE TABLE IF NOT EXISTS pmu (ts TIMESTAMP, mRID VARCHAR, layout VARCHAR, vals DOUBLE[])",
)


def _naive(moment: datetime) -> datetime:
    """UTC without its tzinfo, what the ``ts`` column holds; a naive ``moment`` is taken to be UTC already."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


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


def _layout(header: PmuHeader) -> str:
    """What a segment holds one of: a layout under one grid (``header_id`` leaves the grid out)."""
    return f"{header.header_id}:{header.cimReferenceId}"


class Store:
    """Frames buffered by ``append``, written by ``flush``, read back by ``read``."""

    def __init__(
        self,
        folder: Path,
        *,
        roll: timedelta = timedelta(hours=6),
        flush_every: timedelta = timedelta(seconds=1),
        max_bytes: int = 5 * 1024**3,
        max_buffer: int = 100_000,
    ) -> None:
        self.folder = folder
        self.roll = roll
        self.max_bytes = max_bytes
        self.flush_every = flush_every
        #: Frames kept in memory while the disk refuses them; past it the oldest are dropped.
        self.max_buffer = max_buffer
        self._failing = False
        self._buffer: list[PmuFrame] = []
        self._segment: Path | None = None
        #: The layout and first instant of the segment being written.
        self._layout: str | None = None
        self._start: datetime | None = None
        self._flushed = time.monotonic()

    def append(self, frame: PmuFrame) -> None:
        """Buffer ``frame``; a new layout, or a segment as old as ``roll`` (by frame time), starts a new segment."""
        layout = _layout(frame.header)
        if self._layout is not None and (layout != self._layout or frame.timestamp - self._start >= self.roll):
            self.roll_over()
        if self._layout is None:
            self._layout, self._start = layout, frame.timestamp
        self._buffer.append(frame)
        if len(self._buffer) > self.max_buffer:
            dropped = len(self._buffer) - self.max_buffer
            del self._buffer[:dropped]
            logger.error("recorder %s: the disk is not taking frames; dropped the %d oldest buffered", self.folder, dropped)
        if time.monotonic() - self._flushed >= self.flush_every.total_seconds():
            self.flush()

    def roll_over(self) -> None:
        """Write what is buffered; the next frame opens a new segment."""
        self.flush()
        if self._buffer:
            # The write failed: these belong to the segment that is closing, and must not open the next one.
            logger.error("recorder %s: dropped %d frames that could not be written", self.folder, len(self._buffer))
            self._buffer.clear()
        self._segment = self._layout = self._start = None

    def flush(self) -> None:
        """Write what is buffered. A write the disk refuses is logged and retried at the next flush."""
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
            self._segment = self._free_segment(self._buffer[0].timestamp)
        con = duckdb.connect(str(self._segment))
        try:
            for statement in _SCHEMA:
                con.execute(statement)
            con.begin()  # all or nothing, so a retry after a failure cannot write a frame twice
            for layout, header in {_layout(f.header): f.header for f in self._buffer}.items():
                con.execute("INSERT OR IGNORE INTO layouts VALUES (?, ?)", [layout, header.model_dump_json()])
            con.executemany(
                "INSERT INTO pmu VALUES (?, ?, ?, ?)",
                [[_naive(f.timestamp), f.mRID, _layout(f.header), f.values] for f in self._buffer],
            )
            con.commit()
        finally:
            con.close()

    def _free_segment(self, first: datetime) -> Path:
        """A segment is always a new file: a stream that starts again at the same instant must not append to the old one."""
        name = f"{_naive(first):%Y%m%dT%H%M%S.%f}"
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
        self.flush()
        headers: dict[str, PmuHeader] = {}
        for segment in self.segments():
            con = self._open(segment)
            if con is None:
                continue
            try:
                rows = con.execute(
                    "SELECT p.ts, p.mRID, p.layout, l.header, p.vals FROM pmu p JOIN layouts l ON l.id = p.layout "
                    "WHERE (? IS NULL OR p.ts >= ?) AND (? IS NULL OR p.ts < ?) ORDER BY p.ts",
                    [_naive(start) if start else None] * 2 + [_naive(end) if end else None] * 2,
                ).fetchall()
            finally:
                con.close()
            for ts, mrid, layout, header, values in rows:
                if layout not in headers:
                    headers[layout] = PmuHeader.model_validate_json(header)
                yield PmuFrame(timestamp=ts.replace(tzinfo=UTC), mRID=mrid, header=headers[layout], values=values)

    def bounds(self) -> tuple[datetime, datetime] | None:
        """The first and last instants held, or ``None``."""
        first = last = None
        for segment in self.segments():
            con = self._open(segment)
            if con is None:
                continue
            try:
                low, high = con.execute("SELECT min(ts), max(ts) FROM pmu").fetchone()
            finally:
                con.close()
            if low is not None:
                low, high = low.replace(tzinfo=UTC), high.replace(tzinfo=UTC)
                first = low if first is None else min(first, low)
                last = high if last is None else max(last, high)
        return None if first is None else (first, last)
