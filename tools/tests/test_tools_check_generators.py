"""check-generators' plumbing: the node_modules link, the untracked-file copy, the temp root."""

import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from pswamp_tools import main
from pswamp_tools.commands import check_generators as cg


def test_help_renders():
    result = CliRunner().invoke(main.app, ["check-generators", "--help"])
    assert result.exit_code == 0, result.output
    assert "worktree" in result.output


def test_a_linked_directory_is_removed_without_touching_its_target(tmp_path):
    target = tmp_path / "real"
    (target / "pkg").mkdir(parents=True)
    (target / "pkg" / "index.js").write_text("x", encoding="utf-8")
    link = tmp_path / "tree" / "node_modules"
    link.parent.mkdir()

    if not cg.link_dir(target, link):
        pytest.skip("this platform/user may not create directory links")
    assert cg.is_link(link)
    assert (link / "pkg" / "index.js").read_text(encoding="utf-8") == "x"

    cg.unlink_dir(link)
    assert not link.exists() and not cg.is_link(link)
    assert (target / "pkg" / "index.js").is_file()


def test_unlink_leaves_a_real_directory_alone(tmp_path):
    real = tmp_path / "node_modules"
    real.mkdir()
    cg.unlink_dir(real)
    assert real.is_dir()


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_untracked_files_are_copied_and_ignored_ones_are_not(tmp_path):
    repo, tree = tmp_path / "repo", tmp_path / "tree"
    repo.mkdir()
    tree.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repo / "ignored.txt").write_text("no", encoding="utf-8")
    (repo / "deep" / "er").mkdir(parents=True)
    (repo / "deep" / "er" / "new.py").write_text("yes", encoding="utf-8")

    assert cg.copy_untracked(repo, tree) == 2  # .gitignore and deep/er/new.py
    assert (tree / "deep" / "er" / "new.py").read_text(encoding="utf-8") == "yes"
    assert not (tree / "ignored.txt").exists()


def test_the_temp_root_is_short(monkeypatch, tmp_path):
    monkeypatch.setattr(cg.tempfile, "gettempdir", lambda: str(tmp_path / ("x" * 80)))
    monkeypatch.setattr(cg.Path, "home", lambda: tmp_path)
    assert cg.short_temp_root() == tmp_path / ".pswamp-tmp"
    monkeypatch.setattr(cg.tempfile, "gettempdir", lambda: "C:\\Temp")
    assert str(cg.short_temp_root()) == "C:\\Temp"
