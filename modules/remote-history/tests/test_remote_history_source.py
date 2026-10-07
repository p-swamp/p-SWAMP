"""The remote history source against the stub, in-process, and its failures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from remote_data_stub import create_app

from pydantic import ValidationError

from pswamp_core.playable import Playable
from pswamp_core.settings import MissingSettingError
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.testing import SourceConformance
from pswamp_core.time_range import TimeRange
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.remote_history import RemoteHistory

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
HEADER = PmuHeader(
    station=["A", "A", "B", "B"],
    channel=["V", "f", "V", "f"],
    measurement=["V_Magnitude", "f", "V_Magnitude", "f"],
    units=["kV", "Hz", "kV", "Hz"],
    data_rate=20.0,
)
FRAMES = [
    PmuFrame(timestamp=T0 + timedelta(seconds=i / 20), mRID="served", header=HEADER, values=[400.0, 50.0, 400.0, 50.0])
    for i in range(20)
]


class Served(SourceModule):
    """The history the stub serves: any history source would do."""

    name = "served-frames"
    kind = "history"

    def coverage(self) -> TimeRange:
        return TimeRange(FRAMES[0].timestamp, FRAMES[-1].timestamp + timedelta(seconds=0.05))

    def read(self, start=None, end=None):
        for record in FRAMES:
            if TimeRange(start, end).contains(record.timestamp):
                yield record


def over(app_or_handler) -> RemoteHistory:
    """A source whose connection is ``app_or_handler``: the stub app, or a mock handler."""
    if callable(app_or_handler) and not hasattr(app_or_handler, "routes"):
        transport = httpx.MockTransport(app_or_handler)
    else:
        transport = httpx.ASGITransport(app=app_or_handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://stub")
    return RemoteHistory("remote", url="http://stub", http_client=http)


class TestRemoteHistoryOverTheStub(SourceConformance):
    """The conformance cases, including the sync ``read`` / ``coverage`` that drive
    the async code on a private loop: the in-process stub is loop-agnostic."""

    @pytest.fixture
    def source_under_test(self):
        return over(create_app(Served("served")))

    @pytest.fixture
    def conformance_records(self):
        return FRAMES


class TestTheSampleRecordingFromTheStub(SourceConformance):
    """The bundled sample (the sample-replay project), served by the stub and read back."""

    @pytest.fixture
    def source_under_test(self):
        sample = pytest.importorskip("pswamp_modules.sample_replay")
        return over(create_app(sample.SampleReplay()))

    @pytest.fixture
    def conformance_records(self):
        return list(pytest.importorskip("pswamp_modules.sample_replay").SampleReplay().recording.frames)


def test_a_result_line_has_the_shape_of_its_kind():
    from pswamp_models.remote_data import RemoteDataResult

    assert RemoteDataResult.for_record(FRAMES[0]).to_line().endswith(b"\n")
    for bad in ({"kind": "record"}, {"kind": "end"}, {"kind": "error"}):
        with pytest.raises(ValidationError):
            RemoteDataResult(**bad)


def test_it_is_a_playable_history_source_with_a_required_url():
    assert (RemoteHistory.name, RemoteHistory.kind, RemoteHistory.outputs) == ("remote-history", "history", (PmuFrame,))
    assert issubclass(RemoteHistory, Playable)
    with pytest.raises(MissingSettingError, match="url"):
        RemoteHistory()
    assert RemoteHistory(url="http://x/").url == "http://x" and RemoteHistory(url="u", timeout=5).timeout == 5.0


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("REMOTE_URL", "http://remote-data:8100")
    monkeypatch.setenv("REMOTE_TIMEOUT", "7")
    source = RemoteHistory.from_env("remote")
    assert (source.source, source.url, source.timeout) == ("remote", "http://remote-data:8100", 7.0)


async def test_an_unreachable_service_is_named_in_the_error():
    source = RemoteHistory("remote", url="http://127.0.0.1:9", timeout=2)
    with pytest.raises(ConnectionError, match="127.0.0.1:9"):
        await source.acoverage()


async def test_an_unreachable_service_is_named_when_reading_too():
    source = RemoteHistory("remote", url="http://127.0.0.1:9", timeout=2)
    with pytest.raises(ConnectionError, match="127.0.0.1:9"):
        [r async for r in source.aread()]


def lines(*parts: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"".join(parts))

    return handler


async def test_an_error_line_or_a_missing_end_fails_the_stream():
    from pswamp_models.remote_data import RemoteDataResult

    record = RemoteDataResult.for_record(FRAMES[0]).to_line()
    failed = over(lines(record, RemoteDataResult(kind="error", error="disk on fire").to_line()))
    with pytest.raises(RuntimeError, match="disk on fire"):
        [r async for r in failed.aread()]
    cut = over(lines(record))
    with pytest.raises(RuntimeError, match="without an end line"):
        [r async for r in cut.aread()]


async def test_a_refused_query_says_the_status():
    refused = over(lambda request: httpx.Response(503, text="busy"))
    with pytest.raises(RuntimeError, match="HTTP 503"):
        [r async for r in refused.aread()]


async def test_a_source_set_reads_a_chunk_through_the_service():
    sources = SourceSet([over(create_app(Served("served")))])
    coverage = await sources.coverage()
    chunk = [f async for f in await sources.consume(coverage.start, FRAMES[3].timestamp)]
    assert [f.timestamp for f in chunk] == [f.timestamp for f in FRAMES[:3]]
    await sources.close()
