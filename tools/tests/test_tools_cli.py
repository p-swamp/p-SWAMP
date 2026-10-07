"""The CLI surface: every group and command renders its help, and environment errors are one line."""

import pytest
from typer.testing import CliRunner

from pswamp_tools import main
from pswamp_tools._proc import ToolMissing

runner = CliRunner()

HELP_PAGES = [
    [],
    ["check"],
    ["api"],
    ["api", "generate"],
    ["test"],
    ["test", "server"],
    ["test", "module"],
    ["test", "desktop"],
    ["test", "playwright"],
    ["test", "smoke"],
]


@pytest.mark.parametrize("command", HELP_PAGES, ids=lambda c: " ".join(c) or "pswamp")
def test_help_renders(command):
    result = runner.invoke(main.app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_the_top_level_help_lists_the_groups():
    output = runner.invoke(main.app, ["--help"]).output
    for name in ("check", "api", "test"):
        assert name in output


def test_a_missing_tool_is_an_error_message_not_a_traceback(monkeypatch, capsys):
    def missing(*names, purpose=None):
        raise ToolMissing(list(names), purpose=purpose)

    monkeypatch.setattr("pswamp_tools.commands.test.require_tools", missing)
    with pytest.raises(SystemExit) as caught:
        main.app(["test", "server"], prog_name="pswamp")
    assert caught.value.code == 1
    err = capsys.readouterr().err
    assert "error:" in err and "required tool not found on PATH: uv" in err
    assert "Traceback" not in err


def test_extra_arguments_reach_pytest_verbatim(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("pswamp_tools.commands.test.run", fake_run)
    monkeypatch.setattr("pswamp_tools.commands.test.require_tools", lambda *a, **k: {})
    result = runner.invoke(main.app, ["test", "server", "--", "-k", "lock", "-v"])
    assert result.exit_code == 0, result.output
    assert seen["argv"][-3:] == ["-k", "lock", "-v"]
    result = runner.invoke(main.app, ["test", "server", "-k", "lock"])
    assert seen["argv"][-2:] == ["-k", "lock"]


def test_test_module_runs_one_module_project_s_tests(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("pswamp_tools.commands.test.run", fake_run)
    monkeypatch.setattr("pswamp_tools.commands.test.require_tools", lambda *a, **k: {})
    for name in ("frame-stats", "frame_stats", "modules/frame-stats/"):
        result = runner.invoke(main.app, ["test", "module", name, "-k", "layout"])
        assert result.exit_code == 0, result.output
        tests = seen["argv"][-3].replace("\\", "/")
        assert tests.endswith("modules/frame-stats/tests") and seen["argv"][-2:] == ["-k", "layout"]
    result = runner.invoke(main.app, ["test", "module", "no-such-module"])
    assert result.exit_code == 2 and "frame-stats" in result.output
