"""The remote history source against the stub, in-process, and its failures."""

from __future__ import annotations

import asyncio
import json
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
    data_rate=50.0,
)
FRAMES = [
    PmuFrame(timestamp=T0 + timedelta(milliseconds=20 * i), mRID="remote", header=HEADER, values=[400.0, 50.0, 400.0, 50.0])
    for i in range(20)
]


class Served(SourceModule):
    """The coverage used by the stub's synthetic station stream."""

    name = "served-frames"
    kind = "history"

    def coverage(self) -> TimeRange:
        return TimeRange(FRAMES[0].timestamp, FRAMES[-1].timestamp + timedelta(milliseconds=20))

    def read(self, start=None, end=None):
        for record in FRAMES:
            if TimeRange(start, end).contains(record.timestamp):
                yield record


def over(app_or_handler, queries: list | None = None, **settings) -> RemoteHistory:
    """A source whose connection is ``app_or_handler``: the stub app, or a mock
    handler. ``queries`` collects the body of every query it sends."""
    if callable(app_or_handler) and not hasattr(app_or_handler, "routes"):
        transport = httpx.MockTransport(app_or_handler)
    else:
        transport = httpx.ASGITransport(app=app_or_handler)

    async def record(request: httpx.Request) -> None:
        if queries is not None and request.url.path == "/v1/queries":
            queries.append(json.loads(request.content))

    http = httpx.AsyncClient(transport=transport, base_url="http://stub", event_hooks={"request": [record]})
    return RemoteHistory("remote", url="http://stub", http_client=http, **settings)


class TestRemoteHistoryOverTheStub(SourceConformance):
    """The conformance cases, including the sync ``read`` / ``coverage`` that drive
    the async code on a private loop: the in-process stub is loop-agnostic."""

    @pytest.fixture
    def source_under_test(self):
        return over(create_app(Served("served")))

    @pytest.fixture
    def conformance_records(self):
        return FRAMES


class TestRemoteHistoryInPages(SourceConformance):
    """The same, seven records a query: every range is read as several pages."""

    @pytest.fixture
    def source_under_test(self):
        return over(create_app(Served("served")), page=7)

    @pytest.fixture
    def conformance_records(self):
        return FRAMES


class TestTheSampleRecordingFromTheStub(SourceConformance):
    """The stub's synthetic stream over the bundled sample's coverage."""

    @pytest.fixture
    def source_under_test(self):
        sample = pytest.importorskip("pswamp_modules.sample_replay")
        return over(create_app(sample.SampleReplay()))

    @pytest.fixture
    def conformance_records(self):
        coverage = pytest.importorskip("pswamp_modules.sample_replay").SampleReplay().coverage()
        return [
            FRAMES[0].model_copy(update={"timestamp": coverage.start + timedelta(milliseconds=20 * i)})
            for i in range((coverage.end - coverage.start) // timedelta(milliseconds=20))
        ]


def test_a_result_line_has_the_shape_of_its_kind():
    from pswamp_models.remote_data import RESULT_ADAPTER, RecordResponse

    line = RecordResponse.test_record("q", T0, 1, "NO 12345").to_line()
    assert line.endswith(b"\n") and isinstance(RESULT_ADAPTER.validate_json(line), RecordResponse)
    for bad in ({"kind": "record"}, {"kind": "end"}, {"kind": "error"}):
        with pytest.raises(ValidationError):
            RESULT_ADAPTER.validate_python({"mrid": "q", "v": "v1", "ts": T0, **bad})


def test_it_is_a_playable_history_source_with_a_required_url():
    assert (RemoteHistory.name, RemoteHistory.kind, RemoteHistory.outputs) == ("remote-history", "history", (PmuFrame,))
    assert issubclass(RemoteHistory, Playable)
    with pytest.raises(MissingSettingError, match="url"):
        RemoteHistory()
    assert RemoteHistory(url="http://x/").url == "http://x" and RemoteHistory(url="u", timeout=5).timeout == 5.0


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("REMOTE_URL", "http://remote-data:8100")
    monkeypatch.setenv("REMOTE_TIMEOUT", "7")
    monkeypatch.setenv("REMOTE_COVERAGE_TIMEOUT", "3")
    source = RemoteHistory.from_env("remote")
    assert (source.source, source.url, source.timeout) == ("remote", "http://remote-data:8100", 7.0)
    assert source.coverage_timeout == 3.0 and RemoteHistory(url="u").coverage_timeout == 10.0


async def test_coverage_waits_no_longer_than_its_own_timeout():
    writers = []

    async def accept_and_say_nothing(reader, writer):
        writers.append(writer)
        await reader.read()  # until the client gives up

    server = await asyncio.start_server(accept_and_say_nothing, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
            source = RemoteHistory("remote", url=f"http://127.0.0.1:{port}", http_client=http, coverage_timeout=0.2)
            began = asyncio.get_running_loop().time()
            with pytest.raises(ConnectionError, match="ReadTimeout"):
                await source.acoverage()
            assert asyncio.get_running_loop().time() - began < 2
    finally:
        for writer in writers:
            writer.close()
            await writer.wait_closed()
        server.close()
        await server.wait_closed()


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
    from pswamp_models.remote_data import ErrorMessage, ErrorResponse, RecordResponse

    record = RecordResponse.test_record("q", FRAMES[0].timestamp, 1, "NO 12345").to_line()
    error = ErrorResponse(mrid="q", v="v1", ts=T0, kind="error", msg=ErrorMessage(message="disk on fire"))
    failed = over(lines(record, error.to_line()))
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


# --- pages ---------------------------------------------------------------------------

MICROSECOND = timedelta(microseconds=1)


def starts(queries: list) -> list:
    return [None if q["start"] is None else datetime.fromisoformat(q["start"]) for q in queries]


def serving(frames, *, honour_start=True):
    """A service that ignores ``limit``: every record from the start on, then the end line."""

    def handler(request: httpx.Request) -> httpx.Response:
        from pswamp_models.remote_data import EndMessage, EndResponse, RecordResponse

        start = json.loads(request.content)["start"]
        start = None if start is None or not honour_start else datetime.fromisoformat(start)
        sent = [f for f in frames if start is None or f.timestamp >= start]
        body = b"".join(
            RecordResponse.test_record("q", f.timestamp, i, "NO 12345").to_line() for i, f in enumerate(sent, 1)
        )
        end = EndResponse(mrid="q", v="v1", ts=T0, kind="end", msg=EndMessage(count=len(sent)))
        return httpx.Response(200, content=body + end.to_line())

    return handler


def test_a_page_has_a_positive_size():
    from pswamp_models.remote_data import RemoteDataQuery

    assert RemoteHistory(url="u").page == 30000 and RemoteHistory(url="u", page=7).page == 7
    with pytest.raises(ValueError, match="PAGE"):
        RemoteHistory(url="u", page=0)
    with pytest.raises(ValidationError):
        RemoteDataQuery(limit=0)


def test_the_page_size_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("REMOTE_URL", "http://remote-data:8100")
    monkeypatch.setenv("REMOTE_PAGE", "500")
    assert RemoteHistory.from_env("remote").page == 500


async def test_a_range_is_read_in_pages_each_from_after_the_last_record():
    queries: list = []
    got = [f async for f in over(create_app(Served("served")), queries, page=10).aread()]
    assert [f.timestamp for f in got] == [f.timestamp for f in FRAMES]
    # Two station records per frame: ten records give five complete timestamps.
    assert starts(queries) == [None] + [FRAMES[i].timestamp + MICROSECOND for i in (4, 9, 14, 19)]
    assert [q["limit"] for q in queries] == [10] * 5
    assert all("query_id" not in q and "model" not in q for q in queries)


async def test_a_short_page_is_the_last():
    queries: list = []
    got = [f async for f in over(create_app(Served("served")), queries, page=7).aread()]
    assert len(got) == 20 and len(queries) == 6  # five pages of eight station records, then empty


async def test_no_page_is_asked_for_past_the_end_of_the_range():
    queries: list = []
    end = FRAMES[3].timestamp + MICROSECOND
    got = [f async for f in over(create_app(Served("served")), queries, page=7).aread(None, end)]
    assert len(got) == 4 and len(queries) == 1


async def test_a_service_that_ignores_the_limit_is_read_a_page_at_a_time():
    queries: list = []
    got = [f async for f in over(serving(FRAMES), queries, page=7).aread()]
    assert [f.timestamp for f in got] == [f.timestamp for f in FRAMES]
    assert starts(queries) == [None, FRAMES[6].timestamp + MICROSECOND, FRAMES[13].timestamp + MICROSECOND]


async def test_a_service_that_ignores_the_start_is_caught_not_looped_on():
    source = over(serving(FRAMES, honour_start=False), page=7)
    got: list = []
    with pytest.raises(RuntimeError, match="did not move past"):
        async for frame in source.aread():
            got.append(frame)
    assert [f.timestamp for f in got] == [f.timestamp for f in FRAMES[:7]]  # and no repeats


async def test_the_stub_sends_a_page_and_its_end():
    from pswamp_models.remote_data import RESULT_ADAPTER

    query = {"start": T0.isoformat(), "end": (T0 + timedelta(seconds=1)).isoformat(), "limit": 5}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(Served("served"))), base_url="http://stub") as http:
        response = await http.post("/v1/queries", json=query)
    results = [RESULT_ADAPTER.validate_json(line) for line in response.text.splitlines()]
    assert [r.kind for r in results] == ["record"] * 6 + ["end"] and results[-1].msg.count == 6
    assert response.headers["content-type"] == "application/x-ndjson"
    assert [r.msg.ts for r in results[:-1]] == [FRAMES[i // 2].timestamp for i in range(6)]
    assert [r.msg.id for r in results[:-1]] == ["NO 12345", "NO 54321"] * 3


@pytest.mark.parametrize("request_id", ["caller-request.1", None])
async def test_the_stub_echoes_or_generates_a_request_id(request_id):
    from uuid import UUID

    from pswamp_models.remote_data import RESULT_ADAPTER

    headers = {} if request_id is None else {"x-request-id": request_id}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(Served("served"))), base_url="http://stub"
    ) as http:
        response = await http.post("/v1/queries", json={"limit": 1}, headers=headers)
    assert response.status_code == 200
    returned_id = response.headers["x-request-id"]
    if request_id is None:
        assert str(UUID(returned_id)) == returned_id
    else:
        assert returned_id == request_id
    results = [RESULT_ADAPTER.validate_json(line) for line in response.text.splitlines()]
    assert [r.kind for r in results] == ["record", "record", "end"]
    assert all(r.mrid == returned_id for r in results)


async def test_the_source_sends_a_distinct_request_id_for_each_page():
    request_ids: list[str] = []

    async def record(request: httpx.Request) -> None:
        if request.url.path == "/v1/queries":
            request_ids.append(request.headers["x-request-id"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(Served("served"))),
        base_url="http://stub", event_hooks={"request": [record]},
    ) as http:
        source = RemoteHistory("remote", url="http://stub", http_client=http, page=10)
        frames = [frame async for frame in source.aread()]
    assert len(frames) == len(FRAMES)
    assert len(request_ids) == 5
    run_id = request_ids[0].rsplit(".", 1)[0]
    assert run_id
    assert request_ids == [f"{run_id}.{page}" for page in range(1, 6)]


async def test_station_records_become_one_frame_per_timestamp():
    from pswamp_models.remote_data import RecordResponse

    frames = [f async for f in over(create_app(Served("served")), page=1).aread()]
    assert [f.timestamp for f in frames] == [f.timestamp for f in FRAMES]
    assert all(f.header.stations == ["NO 12345", "NO 54321"] for f in frames)
    assert all(f.header.data_rate == 50.0 and f.header.n_columns == 28 for f in frames)
    first = RecordResponse.test_record("q", T0, 1, "NO 12345").msg
    assert frames[0].values[:4] == [
        first.frequency, first.rocof, first.phasors[0].magnitude / 1000, first.phasors[0].angle,
    ]
    assert frames[0].header.measurement[:4] == ["f", "df", "V_Magnitude", "V_Angle"]
    assert frames[0].header.units[:4] == ["Hz", "Hz/s", "kV", "deg"]
    assert frames[0].header.units[8:10] == ["A", "deg"]


async def test_station_filter_is_applied_before_grouping():
    source = over(create_app(Served("served")))
    frames = [f async for f in source.aread(stations=["NO 54321"])]
    assert len(frames) == len(FRAMES)
    assert all(f.header.stations == ["NO 54321"] for f in frames)


async def test_empty_station_filter_is_rejected():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(Served("served"))), base_url="http://stub"
    ) as http:
        response = await http.post("/v1/queries", json={"stations": []})
    assert response.status_code == 422
    assert any(error["loc"] == ["body", "stations"] for error in response.json()["detail"])
    with pytest.raises(ValidationError):
        [f async for f in over(create_app(Served("served"))).aread(stations=[])]


async def test_duplicate_stations_and_backwards_timestamps_fail():
    from pswamp_models.remote_data import EndMessage, EndResponse, RecordResponse

    first = RecordResponse.test_record("q", T0, 1, "NO 12345").to_line()
    end = EndResponse(mrid="q", v="v1", ts=T0, kind="end", msg=EndMessage(count=2)).to_line()
    with pytest.raises(RuntimeError, match="duplicate station"):
        [f async for f in over(lines(first, first, end)).aread()]
    earlier = RecordResponse.test_record("q", T0 - timedelta(milliseconds=20), 2, "NO 12345").to_line()
    with pytest.raises(RuntimeError, match="timestamp order"):
        [f async for f in over(lines(first, earlier, end)).aread()]
