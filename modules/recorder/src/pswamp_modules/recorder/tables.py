"""``ModelCodec``: a typed table derived from a message class, so a new recordable model needs no storage code.

One table per topic, ``t_<topic with _ for .>``, with ``ts`` (the instant the message is filed under:
its ``timestamp``, or its arrival when it has none), ``arrived``, and one column per field of the
model except ``version``, which a segment's ``meta`` table keeps. The columns are DuckDB's own types,
so the table is queried as it is (``SELECT ts, "result".f_mean FROM t_frame_stats_result WHERE ts >= ...``):

=========================  ==========================
field                      column
=========================  ==========================
``datetime``               ``TIMESTAMP`` (UTC)
``float`` / ``int``        ``DOUBLE`` / ``BIGINT``
``bool`` / ``str``/ enum   ``BOOLEAN`` / ``VARCHAR``
``list[X]``                ``X[]``
a nested model             ``STRUCT(...)``
anything else              ``JSON`` (a ``dict``, a union, ``Any``)
=========================  ==========================

Rows go in ``ts`` order, so DuckDB's zone maps let a time range skip what it does not need.
"""

from __future__ import annotations

import enum
import json
import logging
import types
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypeVar, Union, get_args, get_origin

import duckdb
from pydantic import BaseModel, ValidationError
from pydantic_core import to_json
from pswamp_models.common import DataModel
from pswamp_models.pmu import PmuFrame

from .codecs import READ_BATCH, Codec, Entry, FrameCodec, naive

__all__ = ["ModelCodec", "codec_for", "column_type"]

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=DataModel)

_SCALARS: dict[Any, str] = {datetime: "TIMESTAMP", float: "DOUBLE", int: "BIGINT", bool: "BOOLEAN", str: "VARCHAR"}


def _kind(tp: Any) -> tuple[str, Any]:
    """``(kind, what it wraps)`` for an annotation: ``scalar`` / ``enum`` / ``list`` (its item) / ``struct`` / ``json``."""
    origin = get_origin(tp)
    if origin is Annotated:
        return _kind(get_args(tp)[0])
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        return _kind(args[0]) if len(args) == 1 else ("json", tp)  # an Optional is its type, nullable
    if origin is Literal:
        kinds = {type(v) for v in get_args(tp)}
        return ("scalar", kinds.pop()) if len(kinds) == 1 and next(iter(kinds)) in _SCALARS else ("json", tp)
    if origin in (list, set, frozenset):
        return ("list", get_args(tp)[0]) if get_args(tp) else ("json", tp)
    if isinstance(tp, type):
        if issubclass(tp, BaseModel):
            return "struct", tp
        if issubclass(tp, enum.Enum):
            return "enum", tp
        if tp in _SCALARS:
            return "scalar", tp
    return "json", tp


def column_type(tp: Any) -> str:
    """The DuckDB type a field annotation is stored as (the table above)."""
    kind, inner = _kind(tp)
    if kind == "scalar":
        return _SCALARS[inner]
    if kind == "enum":
        return "VARCHAR"
    if kind == "list":
        return f"{column_type(inner)}[]"
    if kind == "struct":
        return "STRUCT(" + ", ".join(f'"{name}" {column_type(f.annotation)}' for name, f in inner.model_fields.items()) + ")"
    return "JSON"


def _encode(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    kind, inner = _kind(tp)
    if kind == "scalar":
        return naive(value) if inner is datetime else value
    if kind == "enum":
        return value.value if isinstance(value, enum.Enum) else value
    if kind == "list":
        return [_encode(inner, item) for item in value]
    if kind == "struct":
        return {name: _encode(f.annotation, getattr(value, name)) for name, f in inner.model_fields.items()}
    return to_json(value, inf_nan_mode="null").decode()


def _decode(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    kind, inner = _kind(tp)
    if kind == "scalar":
        return value.replace(tzinfo=UTC) if inner is datetime else value
    if kind == "list":
        return [_decode(inner, item) for item in value]
    if kind == "struct":
        return {name: _decode(f.annotation, value.get(name)) for name, f in inner.model_fields.items()}
    if kind == "json":
        return json.loads(value)
    return value


class ModelCodec(Codec[M]):
    """The derived table of one message class."""

    def __init__(self, model: type[M]) -> None:
        self.model = model
        self.table = "t_" + model.topic_name().replace(".", "_")
        self.fields: dict[str, Any] = {name: f.annotation for name, f in model.model_fields.items() if name != "version"}
        self.columns = ", ".join(f'"{name}" {column_type(tp)}' for name, tp in self.fields.items())
        self.version = str(model.model_fields["version"].default)
        #: What a segment's ``meta`` keeps, to know whether it was written by the model as it is now.
        self.signature = f"{self.version}|{self.columns}"

    def time(self, message: M) -> datetime | None:
        return message.timestamp

    def ensure(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("CREATE TABLE IF NOT EXISTS meta (topic VARCHAR PRIMARY KEY, tbl VARCHAR, version VARCHAR, signature VARCHAR)")
        con.execute(f'CREATE TABLE IF NOT EXISTS "{self.table}" (ts TIMESTAMP, arrived TIMESTAMP, {self.columns})')
        con.execute("INSERT OR IGNORE INTO meta VALUES (?, ?, ?, ?)", [self.model.topic_name(), self.table, self.version, self.signature])

    def write(self, con: duckdb.DuckDBPyConnection, entries: Sequence[Entry[M]]) -> None:
        marks = ", ".join("?" * (2 + len(self.fields)))
        rows = [
            [naive(e.ts), naive(e.arrived), *(_encode(tp, getattr(e.message, name)) for name, tp in self.fields.items())]
            for e in sorted(entries, key=lambda e: e.ts)  # in ts order, so a time range reads few row groups
        ]
        con.executemany(f'INSERT INTO "{self.table}" VALUES ({marks})', rows)

    def read_entries(self, con: duckdb.DuckDBPyConnection, start: datetime | None, end: datetime | None) -> Iterator[Entry[M]]:
        try:
            stored = {row[0] for row in con.execute(f'DESCRIBE "{self.table}"').fetchall()}
        except duckdb.CatalogException:  # nothing of this class in the segment, or not made yet
            return
        names = [name for name in self.fields if name in stored]  # a model that gained a field still reads an older segment
        selected = ", ".join(f'"{name}"' for name in names)
        cursor = con.execute(
            f'SELECT ts, arrived, {selected} FROM "{self.table}" '
            "WHERE (? IS NULL OR ts >= ?) AND (? IS NULL OR ts < ?) ORDER BY ts",
            [naive(start) if start else None] * 2 + [naive(end) if end else None] * 2,
        )
        skipped = 0
        while rows := cursor.fetchmany(READ_BATCH):
            for ts, arrived, *row in rows:
                try:
                    message = self.model.model_validate({n: _decode(self.fields[n], v) for n, v in zip(names, row)})
                    yield Entry(message, ts.replace(tzinfo=UTC), arrived.replace(tzinfo=UTC))
                except ValidationError:  # written by a model that no longer reads it
                    skipped += 1
        if skipped:
            logger.warning("recorder: %d %s rows of a segment no longer validate against the model; skipped", skipped, self.model.__name__)

    def bounds(self, con: duckdb.DuckDBPyConnection) -> tuple[datetime, datetime] | None:
        try:
            low, high = con.execute(f'SELECT min(ts), max(ts) FROM "{self.table}"').fetchone()
        except duckdb.CatalogException:
            return None
        if low is None:
            return None
        return low.replace(tzinfo=UTC), high.replace(tzinfo=UTC)


def codec_for(model: type[DataModel]) -> Codec:
    """A frame has its tailored layout; every other recordable message gets its derived table."""
    return FrameCodec() if model is PmuFrame else ModelCodec(model)
