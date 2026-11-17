"""A codec: how one kind of message is laid out in a segment, written and read back.

The store knows segments, buffering, rolling and retention; a codec knows one message class's
table. ``FrameCodec`` is the tailored one for ``PmuFrame`` (a layout stored once, a column of
values per frame as ``DOUBLE[]``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

import duckdb
from pswamp_models.common import DataModel
from pswamp_models.pmu import PmuFrame, PmuHeader

__all__ = ["Codec", "Entry", "FrameCodec", "READ_BATCH", "naive"]

#: Rows a read takes from a segment at a time.
READ_BATCH = 2000

M = TypeVar("M", bound=DataModel)


def naive(moment: datetime) -> datetime:
    """UTC without its tzinfo, what the ``ts`` column holds; a naive ``moment`` is taken to be UTC already."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class Entry(Generic[M]):
    """A message as the store holds it before it is written: when it arrived, and the instant it is filed under
    (its own time, or the arrival of one that carries none)."""

    message: M
    ts: datetime
    arrived: datetime


class Codec(Generic[M]):
    """One message class's storage. A subclass sets ``model`` and ``table``."""

    model: type[M]
    #: The segment's table for this class; also what the store keys a segment's uniformity by.
    table: str

    def time(self, message: M) -> datetime | None:
        """The instant the message itself carries, or ``None`` to be filed under its arrival: what
        segments roll by and reads select on."""
        raise NotImplementedError

    def segment_key(self, message: M) -> str:
        """What must stay the same inside one segment: a message that differs starts a new one."""
        return ""

    def ensure(self, con: duckdb.DuckDBPyConnection) -> None:
        """Create what the segment needs for this class (idempotent)."""
        raise NotImplementedError

    def write(self, con: duckdb.DuckDBPyConnection, entries: Sequence[Entry[M]]) -> None:
        """Insert ``entries``, inside the caller's transaction."""
        raise NotImplementedError

    def read_entries(self, con: duckdb.DuckDBPyConnection, start: datetime | None, end: datetime | None) -> Iterator[Entry[M]]:
        """The segment's messages with ``start <= ts < end``, in ``ts`` order, a batch at a time."""
        raise NotImplementedError

    def read(self, con: duckdb.DuckDBPyConnection, start: datetime | None, end: datetime | None) -> Iterator[M]:
        """``read_entries``, the messages alone."""
        return (entry.message for entry in self.read_entries(con, start, end))

    def bounds(self, con: duckdb.DuckDBPyConnection) -> tuple[datetime, datetime] | None:
        """The first and last instants the segment holds of this class, or ``None``."""
        raise NotImplementedError


class FrameCodec(Codec[PmuFrame]):
    """``pmu(ts, mRID, layout, vals DOUBLE[])`` and ``layouts(id, header)``: each header is kept once."""

    model = PmuFrame
    table = "pmu"

    def time(self, message: PmuFrame) -> datetime | None:
        return message.timestamp

    def segment_key(self, message: PmuFrame) -> str:
        """A layout under one grid (``header_id`` leaves the grid out)."""
        return f"{message.header.header_id}:{message.header.cimReferenceId}"

    def ensure(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("CREATE TABLE IF NOT EXISTS layouts (id VARCHAR PRIMARY KEY, header VARCHAR)")
        con.execute("CREATE TABLE IF NOT EXISTS pmu (ts TIMESTAMP, mRID VARCHAR, layout VARCHAR, vals DOUBLE[])")

    def write(self, con: duckdb.DuckDBPyConnection, entries: Sequence[Entry[PmuFrame]]) -> None:
        for layout, header in {self.segment_key(e.message): e.message.header for e in entries}.items():
            con.execute("INSERT OR IGNORE INTO layouts VALUES (?, ?)", [layout, header.model_dump_json()])
        con.executemany(
            "INSERT INTO pmu VALUES (?, ?, ?, ?)",
            [[naive(e.ts), e.message.mRID, self.segment_key(e.message), e.message.values] for e in entries],
        )

    def read_entries(
        self, con: duckdb.DuckDBPyConnection, start: datetime | None, end: datetime | None
    ) -> Iterator[Entry[PmuFrame]]:
        headers: dict[str, PmuHeader] = {}
        try:
            for layout, header in con.execute("SELECT id, header FROM layouts").fetchall():
                headers[layout] = PmuHeader.model_validate_json(header)
            cursor = con.execute(
                "SELECT ts, mRID, layout, vals FROM pmu "
                "WHERE (? IS NULL OR ts >= ?) AND (? IS NULL OR ts < ?) ORDER BY ts",
                [naive(start) if start else None] * 2 + [naive(end) if end else None] * 2,
            )
        except duckdb.CatalogException:  # the writer made the file and has not made its tables yet: nothing to read
            return
        # A batch at a time: a segment holds hours of frames, and a reader may want the first few.
        while rows := cursor.fetchmany(READ_BATCH):
            for ts, mrid, layout, values in rows:
                moment = ts.replace(tzinfo=UTC)
                frame = PmuFrame(timestamp=moment, mRID=mrid, header=headers[layout], values=values)
                yield Entry(frame, moment, moment)  # a frame is stamped: its arrival is not kept

    def bounds(self, con: duckdb.DuckDBPyConnection) -> tuple[datetime, datetime] | None:
        try:
            low, high = con.execute("SELECT min(ts), max(ts) FROM pmu").fetchone()
        except duckdb.CatalogException:  # not ready yet, as in read
            return None
        if low is None:
            return None
        return low.replace(tzinfo=UTC), high.replace(tzinfo=UTC)
