"""``pswamp dev server --compose-file``: a compose file from outside the repo, its paths its own."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pswamp_tools import _compose_config, main
from pswamp_tools._compose_config import ComposeConfigError, repo_compose_files, resolve, strip_normalisation
from pswamp_tools._docker import Engine
from pswamp_tools.commands import dev

DOCKER = Engine(name="docker", cli="docker", compose=("docker", "compose"))


def test_what_compose_fills_in_is_dropped_and_what_the_file_says_is_kept():
    alone = {
        "name": "proto",
        "networks": {"default": {"name": "proto_default", "ipam": {}}},
        "services": {
            "server": {
                "command": None,
                "entrypoint": None,
                "environment": {"PSWAMP_CIM_PATH": "/grids/g"},
                "networks": {"default": None},
                "volumes": [{"type": "bind", "source": "/proto/grids/g", "target": "/grids/g", "read_only": True}],
            }
        },
    }
    assert strip_normalisation(alone) == {
        "services": {
            "server": {
                "environment": {"PSWAMP_CIM_PATH": "/grids/g"},
                "volumes": [{"type": "bind", "source": "/proto/grids/g", "target": "/grids/g", "read_only": True}],
            }
        }
    }
    own = {"networks": {"default": {}, "grid": {"name": "grid"}}, "services": {"s": {"networks": {"grid": None}}}}
    assert strip_normalisation(own) == {"networks": {"grid": {"name": "grid"}}, "services": {"s": {"networks": {"grid": None}}}}


def test_the_repo_files_are_the_base_then_the_override(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    assert repo_compose_files(tmp_path) == [tmp_path / "docker-compose.yml"]
    (tmp_path / "docker-compose.override.yml").write_text("services: {}\n")
    assert repo_compose_files(tmp_path)[-1] == tmp_path / "docker-compose.override.yml"


def test_each_added_file_is_resolved_in_its_own_folder_then_merged(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docker-compose.yml").write_text("services: {}\n")
    added = tmp_path / "proto" / "compose.override.yml"
    added.parent.mkdir()
    added.write_text("services: {}\n")
    calls = []

    def config(engine, args, cwd, *, partial=False):
        calls.append((args, cwd))
        if partial:
            return {"name": "proto", "services": {"server": {"command": None, "environment": {"A": "1"}}}}
        return {"services": {"server": {}}}

    monkeypatch.setattr(_compose_config, "_config", config)
    assert resolve(DOCKER, repo, [added], tmp_path) == {"services": {"server": {}}}
    (alone, alone_cwd), (merged, merged_cwd) = calls
    assert alone_cwd == added.parent and alone[alone.index("--project-directory") + 1] == str(added.parent)
    assert merged_cwd == repo and merged[-2:] == ["--project-directory", str(repo)]
    piece = Path(merged[merged.index("-f", 2) + 1])
    assert merged[1] == str(repo / "docker-compose.yml")
    assert json.loads(piece.read_text()) == {"services": {"server": {"environment": {"A": "1"}}}}

    with pytest.raises(ComposeConfigError, match="no such file"):
        resolve(DOCKER, repo, [tmp_path / "missing.yml"], tmp_path)


def test_the_server_runs_from_the_resolved_configuration(tmp_path, monkeypatch):
    added = tmp_path / "compose.override.yml"
    added.write_text("services: {}\n")
    monkeypatch.setattr(dev, "find_engine", lambda: DOCKER)
    monkeypatch.setattr(dev, "supports_watch", lambda engine: True)
    monkeypatch.setattr(dev, "resolve", lambda engine, repo, files, scratch: {"services": {"server": {"x": [str(f) for f in files]}}})
    ran = {}

    def run_filtered(command, drop, cwd):
        file = Path(command[command.index("-f") + 1])
        ran.update(command=command, config=json.loads(file.read_text()))
        return 0

    monkeypatch.setattr(dev, "run_filtered", run_filtered)
    result = CliRunner().invoke(main.app, ["dev", "server", "-f", str(added)])
    assert result.exit_code == 0, result.output
    assert ran["config"] == {"services": {"server": {"x": [str(added)]}}}
    assert ran["command"][-3:] == ["up", "--watch", "--build"]
