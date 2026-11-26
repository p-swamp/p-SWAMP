"""`pswamp test load`: its levels, its thresholds and its stats parsing, with no server."""

import pytest

from pswamp_tools import load


def passing(**changes) -> dict:
    """A level's driver summary that meets every threshold, with ``changes``."""
    summary = {
        "clients": 8, "served": 8, "speed": 1.0, "data_rate": 20.0, "failures": [], "close_codes": [],
        "frames_per_s_min": 20.0, "progress_min": 0.999, "stall_share_max": 0.0, "stalls": 0,
        "stats_share_min": 0.999, "switch_s_max": 0.2, "play_s_max": 0.05, "seek_s_max": 0.04,
        "seek_timeouts": 0, "summary_s_max": 0.07, "summary_timeouts": 0, "healthz_ms_p99": 6.0,
        "healthz_failed": 0, "unexpected_notices": {},
    }  # fmt: skip
    return summary | changes


def failed(summary: dict) -> list[str]:
    return [label for label, passed, _ in load.evaluate(summary) if not passed]


def test_clients_are_levels_in_order_each_once():
    assert load.parse_clients("2, 4,8,4") == [2, 4, 8]
    for bad in ("", "0", "2,x", "-1", "2.5"):
        with pytest.raises(ValueError):
            load.parse_clients(bad)


def test_a_healthy_level_passes_every_threshold():
    assert failed(passing()) == []


def test_refused_clients_fail_and_name_the_cap():
    checks = load.evaluate(passing(served=8, clients=16, close_codes=[1013], failures=["RuntimeError: refused"]))
    label, passed, detail = checks[0]
    assert not passed and "8/16" in detail and load.CAP_VARIABLE in detail


def test_nobody_served_is_one_failure_not_a_crash():
    assert failed(passing(served=0, frames_per_s_min=None)) == ["every client is served"]


@pytest.mark.parametrize(
    ("change", "fails"),
    [
        ({"frames_per_s_min": 18.0}, "every frame arrives"),
        ({"progress_min": 0.9}, "playback keeps time"),
        ({"stall_share_max": 0.05, "stalls": 30}, "no stalls"),
        ({"stats_share_min": 0.5}, "modules keep up"),
        ({"switch_s_max": 2.5}, "switch, play and seek"),
        ({"seek_timeouts": 1}, "switch, play and seek"),
        ({"summary_timeouts": 1}, "a range summary"),
        ({"healthz_ms_p99": 250.0}, "the server stays responsive"),
        ({"unexpected_notices": {"frame-stats: failed": 2}}, "nothing unexpected"),
        ({"frames_per_s_min": None}, "every frame arrives"),
    ],
)
def test_each_threshold_fails_on_its_own(change, fails):
    failures = failed(passing(**change))
    assert len(failures) == 1 and failures[0].startswith(fails), failures


def test_the_frame_rate_is_the_sources_times_the_speed():
    assert failed(passing(speed=2.0, frames_per_s_min=39.0, progress_min=1.99)) == []
    assert failed(passing(speed=2.0, frames_per_s_min=30.0, progress_min=1.99)) != []


@pytest.mark.parametrize(
    ("line", "parsed"),
    [
        ("p-swamp-server-1\t35.10%\t216.9MiB / 7.65GiB", ("p-swamp-server-1", 35.1, 216.9)),
        ("kafka\t1.5%\t1.5GiB / 8GiB", ("kafka", 1.5, 1536.0)),
        ("worker\t0.00%\t52.43MB / 8.2GB", ("worker", 0.0, pytest.approx(50.0, abs=0.01))),
        ("not a stats line", None),
        ("x\tn/a\t1MiB / 2MiB", None),
    ],
)
def test_stats_lines(line, parsed):
    assert load.parse_stats_line(line) == parsed


def test_container_figures_only_for_the_compose_stack_here():
    assert load._is_compose_url("http://127.0.0.1:8000") and load._is_compose_url("http://localhost:8000")
    assert not load._is_compose_url("http://127.0.0.1:8200") and not load._is_compose_url("http://p-swamp.example:8000")


def test_the_job_summary_is_a_markdown_table_with_the_failures():
    level = {"summary": passing() | {"switch_s_p50": 0.1, "seek_s_max": 0.04}, "containers": {"server": {"cpu": 19.0, "mem_mib": 131.0}}}
    text = load.markdown([level, level], ["8 clients: no stalls"])
    assert "| Clients | 8 | 8 |" in text
    assert "| server CPU % | 19 | 19 |" in text and "| server MiB | 131 | 131 |" in text
    assert "| worker CPU % | – | – |" in text and "- 8 clients: no stalls" in text


# --- the warm-up's wait for the server's start ----------------------------------------


def answering(monkeypatch, answers: dict[str, list[tuple[int, str]]]) -> list[str]:
    """``http_get`` answering each path in turn from ``answers`` (the last one repeats); the paths asked."""
    asked: list[str] = []

    def http_get(url, timeout=5.0):
        path = url.removeprefix("http://server")
        asked.append(path)
        queue = answers[path]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(load, "http_get", http_get)
    monkeypatch.setattr(load.time, "sleep", lambda _: None)
    return asked


LAYOUT, CHANNELS = (path for path, _ in load.STARTED)


def test_the_wait_ends_when_the_graph_is_loaded_and_the_live_grid_streams(monkeypatch):
    asked = answering(monkeypatch, {
        LAYOUT: [(503, '{"detail": "the grid is loading"}'), (503, '{"detail": "the grid is loading"}'), (200, "{}")],
        CHANNELS: [(503, '{"detail": "the live grid is not streaming yet"}'), (200, "{}")],
    })  # fmt: skip
    assert load.wait_until_started("http://server") == []
    assert asked == [LAYOUT, LAYOUT, LAYOUT, CHANNELS, CHANNELS]


def test_an_app_the_server_does_not_serve_is_not_waited_for(monkeypatch):
    answering(monkeypatch, {LAYOUT: [(404, '{"detail": "Not Found"}')], CHANNELS: [(200, "{}")]})
    notes = load.wait_until_started("http://server")
    assert len(notes) == 1 and "404" in notes[0]


def test_a_grid_that_cannot_be_had_ends_the_wait(monkeypatch):
    asked = answering(monkeypatch, {LAYOUT: [(503, '{"detail": "the grid is not available: no network"}')], CHANNELS: [(200, "{}")]})
    notes = load.wait_until_started("http://server")
    assert asked == [LAYOUT] and "no network" in notes[0]


def test_the_wait_gives_up_at_its_budget_and_says_what_had_not_started(monkeypatch):
    answering(monkeypatch, {LAYOUT: [(503, '{"detail": "the grid is loading"}')], CHANNELS: [(200, "{}")]})
    notes = load.wait_until_started("http://server", budget=0)
    assert len(notes) == 1 and "the CIM graph is loaded" in notes[0] and "the grid is loading" in notes[0]


def test_the_job_summary_carries_the_warm_up_notes():
    level = {"summary": passing(), "containers": {}, "checks": []}
    assert "Warm-up" not in load.markdown([level], [])
    assert "- not started after 180 s" in load.markdown([level], [], ["not started after 180 s: the grid"])
