"""The PMU test streamer: its modules, providers, pipeline and edge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pmu_test_streamer.live_client import LIVE_STREAM_ID, LiveSyntheticClient
from pmu_test_streamer.pipeline import PIPELINE, gateway
from pmu_test_streamer.sample_client import DEFAULT_PATH, EPOCH, STREAM_ID, SampleRecordingClient, load_sample
from pmu_test_streamer.stats_module import FrameStatsModule, FrameStatsResult

from pswamp_core.datagateway import TimeRange
from pswamp_core.host import ModuleHost, serve_hosts
from pswamp_core.messages import PlayCommand, PmuFrame, PmuHeader, SpeedCommand
from pswamp_core.pipeline import PipelineRun
from pswamp_core.testing import DataClientConformance
from pswamp_core.transport import InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

TWO_STATIONS = PmuHeader(
    station=["A", "A", "A", "B", "B", "B"],
    channel=["V", "V", "f", "V", "V", "f"],
    measurement=["V_Magnitude", "V_Angle", "f", "V_Magnitude", "V_Angle", "f"],
    units=["kV", "deg", "Hz", "kV", "deg", "Hz"],
    data_rate=20.0,
)


def synthetic_frame(values: list[float | None], header: PmuHeader = TWO_STATIONS, seconds: float = 0.0) -> PmuFrame:
    return PmuFrame(timestamp=T0 + timedelta(seconds=seconds), mRID="test", header=header, values=values)


async def test_frame_stats_are_computed_from_the_frame_s_own_layout():
    stats = await FrameStatsModule().process(synthetic_frame([400.0, 10.0, 50.0, 410.0, -5.0, 49.8]))
    assert stats.n_stations == 2
    assert round(stats.mean_frequency_hz, 3) == 49.9
    assert (stats.min_frequency_hz, stats.max_frequency_hz) == (49.8, 50.0)
    assert stats.angle_spread_deg == 15.0 and stats.mean_voltage_kv == 405.0


async def test_frame_stats_skip_nulls_and_follow_a_changed_layout():
    module = FrameStatsModule()
    stats = await module.process(synthetic_frame([400.0, 0.0, None, 400.0, 0.0, 50.0]))
    assert stats.n_stations == 1
    one_station = PmuHeader(station=["C"], channel=["f"], measurement=["f"], units=["Hz"], data_rate=20.0)
    stats = await module.process(synthetic_frame([49.5], header=one_station))
    assert (stats.n_stations, stats.mean_frequency_hz, stats.mean_voltage_kv) == (1, 49.5, None)
    assert module.parameters["stations"] == ["C"]


async def test_frame_stats_hosted_over_the_transport():
    broker = InMemoryTransport()
    task = asyncio.create_task(ModuleHost(FrameStatsModule, broker, app="pmu-test-streamer").serve())
    await asyncio.sleep(0)
    with broker.subscribe(FrameStatsResult, app="pmu-test-streamer", key="client-1") as results:
        frame = synthetic_frame([400.0, 1.0, 50.1, 400.0, 2.0, 50.1])
        await broker.publish(frame, app="pmu-test-streamer", key="client-1")
        key, result = await asyncio.wait_for(results.get(), 5)
    await cancel_and_wait(task)
    assert key == "client-1" and result.timestamp == frame.timestamp
    assert result.result.mean_frequency_hz == 50.1 and result.app.name == "frame-stats"


# --- the sample recording ---------------------------------------------------------


def test_the_sample_is_sixty_frames_of_five_stations_at_20_hz():
    recording = load_sample()
    assert len(recording.frames) == 60
    assert recording.header.stations == ["3000", "3245", "5100", "6500", "7000"]
    assert recording.header.data_rate == 20.0 and recording.header.n_columns == 15
    first = recording.frames[0]
    assert first.timestamp == EPOCH + timedelta(seconds=0.05) and first.mRID == STREAM_ID
    assert recording.coverage.end == EPOCH + timedelta(seconds=3.05)


class TestSampleRecordingClient(DataClientConformance):
    @pytest.fixture
    def client_under_test(self):
        return SampleRecordingClient()

    @pytest.fixture
    def conformance_records(self):
        return list(load_sample().frames)


# --- the live feed and the configured sources -------------------------------------


class TestLiveSyntheticClient(DataClientConformance):
    @pytest.fixture
    async def client_under_test(self):
        client = LiveSyntheticClient()
        yield client
        await client.close()


async def test_the_live_feed_ticks_the_sample_s_frames_stamped_now():
    client = LiveSyntheticClient()
    await client.open()
    stream = client.consume(TimeRange(None, None))
    first, second = await anext(stream), await anext(stream)
    await stream.aclose()
    await client.close()
    assert first.mRID == LIVE_STREAM_ID and first.header == load_sample().header
    assert 0.02 < (second.timestamp - first.timestamp).total_seconds() < 0.2


def test_the_streamer_s_sources_are_the_sample_and_the_live_feed(monkeypatch, tmp_path):
    monkeypatch.delenv("PMU_TEST_STREAMER_DATA_CLIENTS", raising=False)
    assert gateway().sources == ["sample", "live"]
    short = tmp_path / "short.txt"
    short.write_text("\n".join(DEFAULT_PATH.read_text().splitlines()[:10]))
    monkeypatch.setenv("PMU_TEST_STREAMER_DATA_CLIENTS", "rec:pmu_test_streamer.sample_client:SampleRecordingClient")
    monkeypatch.setenv("REC_PATH", str(short))
    configured = gateway()
    assert configured.sources == ["rec"] and len(configured.active.recording.frames) == 2


async def test_the_streamer_s_frames_carry_the_cim_reference(monkeypatch):
    monkeypatch.delenv("PMU_TEST_STREAMER_CIM_REFERENCE", raising=False)
    first = await anext(await gateway().consume())
    assert first.header.cimReferenceId == "n44-cim-stub"
    monkeypatch.setenv("PMU_TEST_STREAMER_CIM_REFERENCE", "none")
    assert (await anext(await gateway().consume())).header.cimReferenceId is None


# --- the pipeline ---------------------------------------------------------------------


async def test_a_streamer_run_plays_the_sample_through_frame_stats():
    transport = InMemoryTransport()
    hosts = asyncio.create_task(serve_hosts(PIPELINE.hosts(transport)))
    run = PipelineRun("client-1", PIPELINE, transport)
    await run.start()
    try:
        assert run.player.status().sources == ["sample", "live"]
        assert run.latest.get(PmuFrame).timestamp == EPOCH + timedelta(seconds=0.05)  # shown while paused
        run.dispatch(SpeedCommand(speed=10))
        run.dispatch(PlayCommand())
        for _ in range(200):
            stats = run.latest.get(FrameStatsResult)
            if stats is not None and stats.result.n_stations == 5:
                break
            await asyncio.sleep(0.01)
        assert stats.result.n_stations == 5 and 49 < stats.result.mean_frequency_hz < 51
    finally:
        await run.stop()
        await cancel_and_wait(hosts)


# --- the edge: the socket and the POSTs, in-process ----------------------------------


@pytest.fixture
def server(monkeypatch):
    """The whole server app, in-memory transport, the module hosted in-process."""
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client


def next_state(ws, until=lambda state: True, limit: int = 400) -> dict:
    for _ in range(limit):
        state = ws.receive_json()
        if until(state):
            return state
    raise AssertionError("no such state")


def test_the_socket_opens_on_the_paused_recording(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=101") as ws:
        state = ws.receive_json()
    player = state["player"]
    assert (player["mode"], player["paused"], player["sources"]) == ("replay", True, ["sample", "live"])
    assert (state["frame_index"], state["frame_count"]) == (0, 60)
    assert state["frame"]["header"]["cimReferenceId"] == "n44-cim-stub"


def test_play_brings_frames_and_their_stats(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=102") as ws:
        ws.receive_json()
        assert server.post("/api/pmu-test-streamer/playback/speed?client_id=102", json={"speed": 5}).json() == {
            "status": "ok", "applied": "speed"
        }
        server.post("/api/pmu-test-streamer/playback/play?client_id=102")
        state = next_state(ws, lambda s: s["stats"] is not None and s["frame_index"] >= 3)
        assert state["stats"]["result"]["n_stations"] == 5 and not state["player"]["paused"]
        server.post("/api/pmu-test-streamer/playback/pause?client_id=102")
        next_state(ws, lambda s: s["player"]["paused"])


def test_seek_step_and_a_chunk(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=103") as ws:
        ws.receive_json()
        server.post("/api/pmu-test-streamer/playback/seek?client_id=103", json={"offset_s": 1.5})
        next_state(ws, lambda s: s["frame_index"] == 30)  # 1.5 s after the first frame
        server.post("/api/pmu-test-streamer/playback/step?client_id=103", json={"n": 2})
        next_state(ws, lambda s: s["frame_index"] == 32)
        server.post("/api/pmu-test-streamer/playback/step?client_id=103", json={"n": -1})
        next_state(ws, lambda s: s["frame_index"] == 31)
        server.post("/api/pmu-test-streamer/playback/speed?client_id=103", json={"speed": 10})
        body = {"offset_s": 0.5, "end_offset_s": 1.0, "play": True}
        server.post("/api/pmu-test-streamer/playback/seek?client_id=103", json=body)
        ended = next_state(ws, lambda s: s["player"]["ended"])
        assert ended["frame_index"] == 19 and ended["player"]["paused"]  # the last frame before 1.0 s


def test_live_is_a_source_without_transport_controls(server):
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=104") as ws:
        ws.receive_json()
        server.post("/api/pmu-test-streamer/playback/source?client_id=104", json={"name": "live"})
        state = next_state(ws, lambda s: s["player"]["mode"] == "live" and s["frame"] is not None)
        assert state["frame"]["mRID"] == LIVE_STREAM_ID and state["frame_index"] is None
        refused = server.post("/api/pmu-test-streamer/playback/seek?client_id=104", json={"offset_s": 1})
        assert refused.status_code == 409 and "live" in refused.json()["detail"]
        server.post("/api/pmu-test-streamer/playback/source?client_id=104", json={"name": "sample"})
        back = next_state(ws, lambda s: s["player"]["mode"] == "replay")
        assert back["player"]["paused"]


def test_a_command_needs_an_open_page_and_a_known_source(server):
    assert server.post("/api/pmu-test-streamer/playback/play?client_id=999").status_code == 404
    with server.websocket_connect("/api/pmu-test-streamer/ws?client_id=105") as ws:
        ws.receive_json()
        refused = server.post("/api/pmu-test-streamer/playback/source?client_id=105", json={"name": "nope"})
        assert refused.status_code == 409


def test_a_socket_without_a_client_id_is_refused(server):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as closed:
        with server.websocket_connect("/api/pmu-test-streamer/ws") as ws:
            ws.receive_json()
    assert closed.value.code == 1008


def test_two_clients_on_live_see_one_shared_stream(server):
    with (
        server.websocket_connect("/api/pmu-test-streamer/ws?client_id=201") as first,
        server.websocket_connect("/api/pmu-test-streamer/ws?client_id=202") as second,
    ):
        first.receive_json()
        second.receive_json()
        for client in ("201", "202"):
            server.post(f"/api/pmu-test-streamer/playback/source?client_id={client}", json={"name": "live"})
        a = next_state(first, lambda s: s["player"]["mode"] == "live" and s["stats"] is not None)
        b = next_state(second, lambda s: s["player"]["mode"] == "live" and s["stats"] is not None)
        assert a["stats"]["app"]["uuid"] == b["stats"]["app"]["uuid"]  # one module instance for both
        first_seen = {next_state(first)["frame"]["timestamp"] for _ in range(20)}
        second_seen = {next_state(second)["frame"]["timestamp"] for _ in range(20)}
        assert first_seen & second_seen  # the same frames, stamped once by the shared run
