"""Repo root discovery: from any subdirectory, and from the installed package as a fallback."""

from pathlib import Path

import pytest

from pswamp_tools import _paths

REPO = Path(__file__).resolve().parents[2]


def fake_repo(root: Path) -> Path:
    (root / "app" / "server-python").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["core"]\n', encoding="utf-8")
    return root


def test_the_real_repo_is_found_from_a_deep_subdirectory():
    assert _paths.find_repo_root(REPO / "core" / "src" / "pswamp_core") == REPO


def test_a_member_manifest_is_not_mistaken_for_the_root():
    assert not _paths.is_repo_root(REPO / "core")
    assert _paths.is_repo_root(REPO)


def test_a_workspace_root_is_found_walking_up(tmp_path):
    root = fake_repo(tmp_path / "clone")
    deep = root / "a" / "b"
    deep.mkdir(parents=True)
    assert _paths.find_repo_root(deep) == root.resolve()


def test_outside_any_repo_it_falls_back_to_where_the_package_lives(tmp_path):
    assert _paths.find_repo_root(tmp_path) == REPO


def test_nowhere_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(_paths, "__file__", str(tmp_path / "pkg" / "_paths.py"))
    with pytest.raises(_paths.RepoNotFound, match="Run pswamp from inside the repo"):
        _paths.find_repo_root(tmp_path)


def test_a_broken_manifest_is_not_a_root(tmp_path):
    root = fake_repo(tmp_path)
    (root / "pyproject.toml").write_text("not [ toml", encoding="utf-8")
    assert not _paths.is_repo_root(root)
