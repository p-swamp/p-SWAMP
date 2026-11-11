"""The recordings on disk: DuckDB files, one per segment, in one folder.

A connection is opened per call and closed again, so a reader never meets a
writer's open file, in this process or another.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
from pswamp_models.pmu import PmuFrame, PmuHeader

__all__ = ["Store"]

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS layouts (id VARCHAR PRIMARY KEY, header VARCHAR)",
    "CREATE TABLE IF NOT EXISTS pmu (ts TIMESTAMP, mRID VARCHAR, layout VARCHAR, vals DOUBLE[])",
)


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


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
    ) -> None:
        self.folder = folder
        self.roll = roll
        self.max_bytes = max_bytes
        self.flush_every = flush_every
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
        if time.monotonic() - self._flushed >= self.flush_every.total_seconds():
            self.flush()

    def roll_over(self) -> None:
        """Write what is buffered; the next frame opens a new segment."""
        self.flush()
        self._segment = self._layout = self._start = None

    def flush(self) -> None:
        self._flushed = time.monotonic()
        if not self._buffer:
            return
        if self._segment is None:
            self.folder.mkdir(parents=True, exist_ok=True)
            self._segment = self.folder / f"{_naive(self._buffer[0].timestamp):%Y%m%dT%H%M%S.%f}.duckdb"
        con = duckdb.connect(str(self._segment))
        try:
            for statement in _SCHEMA:
                con.execute(statement)
            for frame in self._buffer:
                con.execute(
                    "INSERT OR IGNORE INTO layouts VALUES (?, ?)", [_layout(frame.header), frame.header.model_dump_json()]
                )
            con.executemany(
                "INSERT INTO pmu VALUES (?, ?, ?, ?)",
                [[_naive(f.timestamp), f.mRID, _layout(f.header), f.values] for f in self._buffer],
            )
        finally:
            con.close()
        self._buffer.clear()
        self._sweep()

    def _sweep(self) -> None:
        """Delete the oldest segments while the folder is over ``max_bytes``; never the open one."""
        closed = [path for path in self.segments() if path != self._segment]
        total = sum(path.stat().st_size for path in self.segments())
        for path in closed:
            if total <= self.max_bytes:
                return
            total -= path.stat().st_size
            path.unlink()

    def segments(self) -> list[Path]:
        return sorted(self.folder.glob("*.duckdb"))

    def read(self, start: datetime | None = None, end: datetime | None = None) -> Iterator[PmuFrame]:
        self.flush()
        headers: dict[str, PmuHeader] = {}
        for segment in self.segments():
            con = duckdb.connect(str(segment))
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
            con = duckdb.connect(str(segment))
            try:
                low, high = con.execute("SELECT min(ts), max(ts) FROM pmu").fetchone()
            finally:
                con.close()
            if low is not None:
                low, high = low.replace(tzinfo=UTC), high.replace(tzinfo=UTC)
                first = low if first is None else min(first, low)
                last = high if last is None else max(last, high)
        return None if first is None else (first, last)
