"""The error tray: notices per client, forwarded from the pipelines' error topics."""

from __future__ import annotations

import pytest
from errors import ErrorHub

from pswamp_core.util.time import utcnow
from pswamp_models.common import ErrorEvent


def event(message: str = "it broke") -> ErrorEvent:
    return ErrorEvent(timestamp=utcnow(), source="player", message=message, detail="Boom: x", request_id="r1")


def test_the_hub_keeps_the_last_notices_per_client_and_feeds_open_trays():
    hub = ErrorHub(keep=2)
    with hub.tray("c1") as tray:
        notice = hub.publish("c1", "app", event("one"))
        assert tray.get_nowait() == notice and (notice.app, notice.request_id) == ("app", "r1")
    hub.publish("c1", "app", event("two"))
    hub.publish("c1", "app", event("three"))
    assert [n.message for n in hub.recent("c1")] == ["two", "three"]
    assert hub.recent("c2") == []


@pytest.fixture
def server(monkeypatch):
    monkeypatch.delenv("PSWAMP_TRANSPORT", raising=False)
    from fastapi.testclient import TestClient

    import server as server_module

    with TestClient(server_module.app) as client:
        yield client


def test_a_refused_module_command_reaches_the_client_s_tray(server):
    with (
        server.websocket_connect("/api/pmu-test-streamer/ws?client_id=401") as page,
        server.websocket_connect("/api/errors/ws?client_id=401") as tray,
    ):
        page.receive_json()
        body = {"source": "live", "offset_s": 0, "end_offset_s": 1}
        ack = server.post("/api/pmu-test-streamer/summary?client_id=401", json=body).json()
        notice = tray.receive_json()
    assert (notice["app"], notice["source"]) == ("pmu-test-streamer", "range-summary")
    assert "live" in notice["detail"] and notice["request_id"] == ack["request_id"]


def test_a_command_the_transport_does_not_take_reaches_the_tray_directly(server, monkeypatch):
    import shared
    from pmu_test_streamer import api

    from pswamp_models.common import Command

    link = shared.transport()
    publish = link.publish

    async def no_commands(message, *, app, key):
        if isinstance(message, Command):
            raise ConnectionError("broker down")
        await publish(message, app=app, key=key)

    with (
        server.websocket_connect("/api/pmu-test-streamer/ws?client_id=402") as page,
        server.websocket_connect("/api/errors/ws?client_id=402") as tray,
    ):
        page.receive_json()
        api.REGISTRY.peek("402").outbox.deadline = 0.1
        monkeypatch.setattr(link, "publish", no_commands)  # the error topic is on it too
        ack = server.post("/api/pmu-test-streamer/playback/play?client_id=402")
        notice = tray.receive_json()
    assert ack.status_code == 200 and notice["request_id"] == ack.json()["request_id"]
    assert notice["source"] == "server" and "not delivered" in notice["message"]
    assert notice["detail"] == "ConnectionError: broker down"
