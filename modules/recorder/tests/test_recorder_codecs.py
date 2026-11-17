"""A segment's layout on disk, and the store's contract with a codec."""

from datetime import UTC, datetime, timedelta

import duckdb
import pytest
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_models.scada import ScadaScan
from pswamp_modules.recorder.codecs import FrameCodec
from pswamp_modules.recorder.store import Store

T0 = datetime(2026, 3, 14, 13, 5, tzinfo=UTC)
HEADER = PmuHeader(station=["3000"], channel=["f"], measurement=["f"], units=["Hz"], data_rate=50.0)


def frame(i: int) -> PmuFrame:
    return PmuFrame(timestamp=T0 + timedelta(milliseconds=20 * i), mRID="test", header=HEADER, values=[50.0 + i / 1000])


def test_a_frame_segment_is_the_pmu_and_layouts_tables(tmp_path):
    store = Store(tmp_path)
    store.append(frame(0))
    store.flush()
    (segment,) = store.segments()
    con = duckdb.connect(str(segment))
    try:
        tables = {row[0]: [(c[0], c[1]) for c in con.execute(f"DESCRIBE {row[0]}").fetchall()] for row in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()
    assert tables == {
        "layouts": [("id", "VARCHAR"), ("header", "VARCHAR")],
        "pmu": [("ts", "TIMESTAMP"), ("mRID", "VARCHAR"), ("layout", "VARCHAR"), ("vals", "DOUBLE[]")],
    }


def test_a_segment_written_by_hand_in_that_layout_is_read(tmp_path):
    """What an earlier version wrote stays readable."""
    first = frame(0)
    con = duckdb.connect(str(tmp_path / "20260314T130500.000000.duckdb"))
    con.execute("CREATE TABLE layouts (id VARCHAR PRIMARY KEY, header VARCHAR)")
    con.execute("CREATE TABLE pmu (ts TIMESTAMP, mRID VARCHAR, layout VARCHAR, vals DOUBLE[])")
    layout = FrameCodec().segment_key(first)
    con.execute("INSERT INTO layouts VALUES (?, ?)", [layout, HEADER.model_dump_json()])
    con.execute("INSERT INTO pmu VALUES (?, ?, ?, ?)", [datetime(2026, 3, 14, 13, 5), "test", layout, first.values])
    con.close()
    assert list(Store(tmp_path).read()) == [first]
    assert Store(tmp_path).bounds() == (first.timestamp, first.timestamp)


def test_the_store_refuses_a_message_it_has_no_codec_for(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(TypeError, match="ScadaScan"):
        store.append(ScadaScan(source="x"))
    assert store.segments() == []


def test_the_codec_a_store_is_given_replaces_the_default(tmp_path):
    store = Store(tmp_path, codecs=())
    with pytest.raises(TypeError):
        store.append(frame(0))
    assert list(store.read()) == [] and store.bounds() is None
