"""``pswamp dev server --extra-modules``: finding the projects, and the compose configuration."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pswamp_tools import _paths, main
from pswamp_tools._docker import Engine
from pswamp_tools._extra_modules import (
    CONTAINER_ROOT,
    WORKER,
    ExtraModulesError,
    read_extra_modules,
    variable_for,
    with_extra_modules,
)
from pswamp_tools.commands import dev

MANIFEST = """
[project]
name = "{name}"
version = "0.1.0"

[project.entry-points."pswamp.modules"]
{modules}
"""


def project(path: Path, *modules: str) -> Path:
    path.mkdir(parents=True)
    (path / "src").mkdir()
    entries = "\n".join(f'{m} = "pkg:Cls"' for m in modules)
    (path / "pyproject.toml").write_text(MANIFEST.format(name=path.name, modules=entries), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    project(root / "modules" / "frame-stats", "frame-stats")
    return root


def test_one_project_or_a_folder_of_them(tmp_path, repo):
    one = project(tmp_path / "proto", "my-module", "other-module")
    [found] = read_extra_modules(one, repo)
    assert (found.host, found.container, found.modules) == (one, CONTAINER_ROOT, ("my-module", "other-module"))

    folder = tmp_path / "many"
    project(folder / "b", "b-module")
    project(folder / "a", "a-module")
    project(folder / "no-modules")  # a project with no module is skipped
    (folder / "notes").mkdir()
    found = read_extra_modules(folder, repo)
    assert [(p.container, p.modules) for p in found] == [
        (f"{CONTAINER_ROOT}/a", ("a-module",)),
        (f"{CONTAINER_ROOT}/b", ("b-module",)),
    ]


def test_what_cannot_be_used_says_why(tmp_path, repo):
    with pytest.raises(ExtraModulesError, match="is not a folder"):
        read_extra_modules(tmp_path / "missing", repo)
    (tmp_path / "empty").mkdir()
    with pytest.raises(ExtraModulesError, match="holds no pyproject.toml"):
        read_extra_modules(tmp_path / "empty", repo)
    with pytest.raises(ExtraModulesError, match="declares a module"):
        read_extra_modules(project(tmp_path / "plain"), repo)
    with pytest.raises(ExtraModulesError, match="frame-stats: already a module of this repo"):
        read_extra_modules(project(tmp_path / "clash", "frame-stats"), repo)


def test_the_variable_is_spelled_as_the_core_spells_it():
    assert variable_for("grid-monitor") == "GRID_MONITOR_EXTRA_MODULES"
    from pswamp_core.settings import env_key  # the core's own spelling, which the pipeline reads

    assert variable_for("pmu-test-streamer") == env_key("pmu-test-streamer", "EXTRA_MODULES")


CONFIG = {
    "name": "p-swamp",
    "services": {
        "server": {
            "build": {"context": "/repo", "dockerfile": "Dockerfile"},
            "image": "p-swamp:latest",
            "environment": {"PSWAMP_TRANSPORT": "kafka"},
            "develop": {"watch": [{"path": "/repo/core/src", "action": "sync", "target": "/x"}]},
        },
        "module-worker": {
            "build": {"context": "/repo", "dockerfile": "Dockerfile"},
            "image": "p-swamp:latest",
            "command": ["python", "-m", "pswamp_core.worker"],
            "environment": {
                "PSWAMP_TRANSPORT": "kafka",
                "PSWAMP_WORKER_PIPELINES": "pmu-test-streamer.toml,grid-monitor.toml",
                "PSWAMP_WORKER_MODULES": "frame-stats,line-outage",
            },
            "develop": {"watch": [{"path": "/repo/core/src", "action": "sync+restart", "target": "/x"}]},
        },
        "kafka": {"image": "apache/kafka"},
    },
}


def test_the_configuration_builds_every_image_with_the_modules_and_adds_their_worker(tmp_path, repo):
    proto = project(tmp_path / "proto", "my-module")
    projects = read_extra_modules(proto, repo)
    config = with_extra_modules(CONFIG, proto, projects, "grid-monitor")
    services = config["services"]

    assert "additional_contexts" not in CONFIG["services"]["server"]["build"]  # the input is untouched
    assert "build" not in services["kafka"] and "environment" not in services["kafka"]
    for name in ("server", "module-worker", WORKER):
        assert services[name]["build"]["additional_contexts"] == {"extra-modules": str(proto)}
        assert services[name]["environment"]["GRID_MONITOR_EXTRA_MODULES"] == "my-module"

    worker = services[WORKER]
    assert worker["command"] == ["python", "-m", "pswamp_core.worker"]
    assert worker["environment"]["PSWAMP_TRANSPORT"] == "kafka"  # the rest is module-worker's
    assert worker["environment"]["PSWAMP_WORKER_PIPELINES"] == "grid-monitor.toml"
    assert worker["environment"]["PSWAMP_WORKER_MODULES"] == "my-module"
    assert services["module-worker"]["environment"]["PSWAMP_WORKER_MODULES"] == "frame-stats,line-outage"
    assert worker["develop"]["watch"][-2:] == [
        {"path": str(proto / "src"), "action": "sync+restart", "target": f"{CONTAINER_ROOT}/src"},
        {"path": str(proto / "pyproject.toml"), "action": "rebuild"},
    ]
    assert services["server"]["develop"]["watch"][-1] == {
        "path": str(proto / "src"), "action": "sync", "target": f"{CONTAINER_ROOT}/src"
    }


def test_the_configuration_needs_a_worker_to_copy_and_a_free_name(tmp_path, repo):
    projects = read_extra_modules(project(tmp_path / "proto", "my-module"), repo)
    with pytest.raises(ExtraModulesError, match="no module-worker"):
        with_extra_modules({"services": {}}, tmp_path, projects, "grid-monitor")
    taken = {"services": {**CONFIG["services"], WORKER: {}}}
    with pytest.raises(ExtraModulesError, match="already has a service named"):
        with_extra_modules(taken, tmp_path, projects, "grid-monitor")


def test_the_server_command_runs_from_the_one_file_at_the_repo_root(tmp_path):
    engine = Engine(name="docker", cli="docker", compose=("docker", "compose"))
    file = tmp_path / "compose.json"
    assert dev.server_command(engine, watch=True, compose_file=file) == [
        "docker", "compose", "-f", str(file), "--project-directory", str(_paths.repo_root()), "up", "--watch", "--build",
    ]


def test_a_missing_pipeline_is_refused_before_compose_is_asked(tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "find_engine", lambda: Engine("docker", "docker", ("docker", "compose")))
    monkeypatch.setattr(dev, "supports_watch", lambda engine: True)
    proto = project(tmp_path / "proto", "my-module")
    result = CliRunner().invoke(main.app, ["dev", "server", "--extra-modules", str(proto), "--pipeline", "nope"])
    assert result.exit_code == 2
    assert "pipelines/nope.toml" in result.output
