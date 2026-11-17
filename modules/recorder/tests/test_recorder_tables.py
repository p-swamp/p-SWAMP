"""The table derived from a message class: its types, its round trip, and a segment that outlives its model."""

from datetime import UTC, datetime, timedelta
from typing import Literal

import duckdb
from pswamp_models.cim import CimEdits
from pswamp_models.common import DataModel
from pswamp_models.frame_stats import FrameStatsResult
from pswamp_models.rtsim import SimEvent
from pswamp_models.scada import AnalogReading, DiscreteReading, ScadaScan
from pswamp_modules.recorder.store import Store
from pswamp_modules.recorder.tables import ModelCodec, codec_for, column_type

T0 = datetime(2026, 3, 14, 13, 5, tzinfo=UTC)


def scan(i: int, *, stamped: bool = True) -> ScadaScan:
    return ScadaScan(
        timestamp=T0 + timedelta(seconds=2 * i) if stamped else None,
        source="rtsim",
        sim_time=2.0 * i,
        analogs=[AnalogReading(mRID="a1", value=1.5 + i), AnalogReading(mRID="a2", value=-2.0)],
        discretes=[DiscreteReading(mRID="d1", value=1)],
    )


def test_a_field_is_stored_as_the_matching_duckdb_type():
    assert column_type(float) == "DOUBLE" and column_type(int) == "BIGINT" and column_type(bool) == "BOOLEAN"
    assert column_type(datetime | None) == "TIMESTAMP"
    assert column_type(list[float]) == "DOUBLE[]"
    assert column_type(Literal["a", "b"]) == "VARCHAR"
    assert column_type(list[DiscreteReading]) == 'STRUCT("mRID" VARCHAR, "value" BIGINT)[]'
    assert column_type(dict[str, float]) == "JSON" and column_type(int | str) == "JSON"


def test_a_scan_round_trips_through_its_table(tmp_path):
    store = Store(tmp_path, codecs=[codec_for(ScadaScan)])
    sent = [scan(i) for i in range(3)]
    for each in sent:
        store.append(each)
    store.flush()
    (segment,) = store.segments()
    con = duckdb.connect(str(segment))
    try:
        assert con.execute("SELECT topic, tbl, version FROM meta").fetchall() == [("scada.scan", "t_scada_scan", "v1")]
        assert con.execute("SELECT count(*), min(ts) FROM t_scada_scan").fetchone()[0] == 3
        codec = ModelCodec(ScadaScan)
        got = list(codec.read(con, None, None))
        assert got == sent
        assert list(codec.read(con, T0 + timedelta(seconds=2), T0 + timedelta(seconds=4))) == [got[1]]
        assert codec.bounds(con) == (sent[0].timestamp, sent[2].timestamp)
    finally:
        con.close()


def test_a_message_with_no_timestamp_is_filed_under_its_arrival(tmp_path):
    store = Store(tmp_path, codecs=[codec_for(ScadaScan)])
    before = datetime.now(UTC)
    store.append(scan(0, stamped=False))
    store.flush()
    (segment,) = store.segments()
    con = duckdb.connect(str(segment))
    try:
        low, high = ModelCodec(ScadaScan).bounds(con)
        assert before <= low <= datetime.now(UTC) and low == high
        (back,) = ModelCodec(ScadaScan).read(con, None, None)
        assert back.timestamp is None  # what was sent, not where it was filed
    finally:
        con.close()


def test_rows_are_written_in_time_order(tmp_path):
    store = Store(tmp_path, codecs=[codec_for(ScadaScan)])
    for i in (2, 0, 1):
        store.append(scan(i))
    store.flush()
    con = duckdb.connect(str(store.segments()[0]))
    try:
        assert [row[0] for row in con.execute("SELECT sim_time FROM t_scada_scan").fetchall()] == [0.0, 2.0, 4.0]
    finally:
        con.close()


def test_every_other_recordable_message_gets_a_table(tmp_path):
    store = Store(tmp_path, codecs=[codec_for(SimEvent), codec_for(CimEdits), codec_for(FrameStatsResult)])
    assert {c.table for c in store.codecs.values()} == {"t_sim_event", "t_cim_edits", "t_frame_stats_result"}


def test_a_new_message_class_needs_no_storage_code(tmp_path):
    class Alarm(DataModel):
        recordable = True
        version: Literal["v2"] = "v2"
        severity: int
        text: str
        tags: list[str] = []
        extra: dict[str, float] | None = None

    sent = Alarm(timestamp=T0, mRID="x", severity=3, text="line out", tags=["a", "b"], extra={"k": 1.0})
    store = Store(tmp_path, codecs=[codec_for(Alarm)])
    store.append(sent)
    store.flush()
    con = duckdb.connect(str(store.segments()[0]))
    try:
        assert con.execute("SELECT version FROM meta").fetchone() == ("v2",)
        assert list(ModelCodec(Alarm).read(con, None, None)) == [sent]
    finally:
        con.close()


def test_a_segment_written_by_an_older_model_still_reads(tmp_path):
    class Reading(DataModel):
        version: Literal["v1"] = "v1"
        n: int

    store = Store(tmp_path, codecs=[codec_for(Reading)])
    for i in range(2):
        store.append(Reading(timestamp=T0 + timedelta(seconds=i), n=i))
    store.flush()
    (segment,) = store.segments()

    class Reading(DataModel):  # noqa: F811 -- the model after a change: a new field with a default
        version: Literal["v1"] = "v1"
        n: int
        unit: str = "Hz"

    con = duckdb.connect(str(segment))
    try:
        assert [r.n for r in ModelCodec(Reading).read(con, None, None)] == [0, 1]
        assert {r.unit for r in ModelCodec(Reading).read(con, None, None)} == {"Hz"}
    finally:
        con.close()
