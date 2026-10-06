"""Finding and running tools: clear errors for missing ones, exit codes passed through."""

import sys

import pytest

from pswamp_tools import _proc


def no_tools(monkeypatch, present=()):
    monkeypatch.setattr(_proc.shutil, "which", lambda name: f"/bin/{name}" if name in present else None)


def test_a_missing_tool_names_itself_and_how_to_install_it(monkeypatch):
    no_tools(monkeypatch)
    with pytest.raises(_proc.ToolMissing) as caught:
        _proc.require_tool("npm", purpose="by pswamp check")
    message = str(caught.value)
    assert "required tool not found on PATH: npm" in message
    assert "(needed by pswamp check)" in message
    assert "Node.js" in message


def test_an_explicit_hint_replaces_the_default(monkeypatch):
    no_tools(monkeypatch)
    with pytest.raises(_proc.ToolMissing, match="-> brew install thing"):
        _proc.require_tool("thing", "brew install thing")


def test_every_missing_tool_is_reported_at_once(monkeypatch):
    no_tools(monkeypatch, present=("uv",))
    with pytest.raises(_proc.ToolMissing) as caught:
        _proc.require_tools("uv", "npm", "npx")
    assert caught.value.names == ["npm", "npx"]
    assert "required tools not found on PATH: npm, npx" in str(caught.value)
    assert str(caught.value).count("Node.js") == 1  # one hint, not one per tool


def test_a_present_tool_resolves_to_its_full_path(monkeypatch):
    no_tools(monkeypatch, present=("npx",))
    assert _proc.require_tool("npx") == "/bin/npx"


def test_children_get_utf8_and_no_foreign_virtualenv(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/else")
    env = _proc.child_env({"EXTRA": "1"})
    assert env["PYTHONUTF8"] == "1" and env["EXTRA"] == "1"
    assert "VIRTUAL_ENV" not in env


def test_run_returns_the_exit_code():
    assert _proc.run([sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert _proc.run([sys.executable, "-c", "pass"]) == 0


def test_a_quiet_run_still_shows_the_output_of_a_failure(capsys):
    _proc.run([sys.executable, "-c", "print('quiet-ok')"], quiet=True)
    assert "quiet-ok" not in capsys.readouterr().out
    _proc.run([sys.executable, "-c", "print('it broke ✓'); raise SystemExit(1)"], quiet=True)
    assert "it broke ✓" in capsys.readouterr().out


def test_running_a_missing_program_is_a_tool_error_not_a_traceback(monkeypatch):
    no_tools(monkeypatch)
    with pytest.raises(_proc.ToolMissing, match="uv"):
        _proc.run(["uv", "--version"])
