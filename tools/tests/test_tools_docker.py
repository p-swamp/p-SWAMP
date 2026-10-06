"""Container engine detection: docker, podman, podman behind a `docker` alias, and nothing."""

import pytest

from pswamp_tools import _docker


def environment(monkeypatch, on_path: dict[str, str], answers: dict[tuple[str, ...], str]):
    """``on_path``: tool -> path. ``answers``: argv that succeed -> their output; anything else fails."""
    monkeypatch.setattr(_docker.shutil, "which", lambda name: on_path.get(name))

    def fake_answers(argv):
        key = tuple(argv)
        return (key in answers, answers.get(key, ""))

    monkeypatch.setattr(_docker, "_answers", fake_answers)


def test_docker_with_the_compose_plugin(monkeypatch):
    environment(
        monkeypatch,
        {"docker": "D"},
        {("D", "--version"): "Docker version 27.0.1", ("D", "compose", "version"): "v2"},
    )
    engine = _docker.find_engine()
    assert (engine.name, engine.cli, engine.compose, engine.is_podman) == ("docker", "D", ("D", "compose"), False)


def test_docker_falls_back_to_standalone_docker_compose(monkeypatch):
    environment(
        monkeypatch,
        {"docker": "D", "docker-compose": "DC"},
        {("D", "--version"): "Docker version 27", ("DC", "version"): "v1"},
    )
    assert _docker.find_engine().compose == ("DC",)


def test_podman_installed_as_docker_is_podman(monkeypatch):
    environment(
        monkeypatch,
        {"docker": "D"},
        {("D", "--version"): "podman version 5.2.0", ("D", "compose", "version"): "ok"},
    )
    engine = _docker.find_engine()
    assert engine.is_podman and engine.cli == "D" and engine.compose == ("D", "compose")


def test_podman_alone(monkeypatch):
    environment(
        monkeypatch,
        {"podman": "P"},
        {("P", "--version"): "podman version 6.0.2", ("P", "compose", "version"): "Docker Compose v5"},
    )
    engine = _docker.find_engine()
    assert (engine.name, engine.compose) == ("podman", ("P", "compose"))


def test_podman_without_a_compose_provider_tries_podman_compose(monkeypatch):
    environment(
        monkeypatch,
        {"podman": "P", "podman-compose": "PC"},
        {("P", "--version"): "podman version 6", ("PC", "version"): "podman-compose 1.2"},
    )
    assert _docker.find_engine().compose == ("PC",)


def test_a_docker_that_does_not_run_falls_through_to_podman(monkeypatch):
    environment(
        monkeypatch,
        {"docker": "D", "podman": "P"},
        {("P", "--version"): "podman version 6", ("P", "compose", "version"): "ok"},
    )
    assert _docker.find_engine().cli == "P"


def test_no_engine_is_a_clear_error(monkeypatch):
    environment(monkeypatch, {}, {})
    with pytest.raises(_docker.ContainerToolMissing, match="neither `docker` nor `podman`") as caught:
        _docker.find_engine()
    assert "podman.io" in str(caught.value)


def test_an_engine_without_compose_says_what_was_tried(monkeypatch):
    environment(monkeypatch, {"podman": "P"}, {("P", "--version"): "podman version 6"})
    with pytest.raises(_docker.ContainerToolMissing) as caught:
        _docker.find_engine()
    message = str(caught.value)
    assert "no working compose command" in message and "P compose" in message
    assert "podman-compose" in message and "podman machine start" in message
