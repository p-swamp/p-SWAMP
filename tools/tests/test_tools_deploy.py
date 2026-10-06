"""``pswamp deploy``: missing tools, the build-log check, and the port-forward lifecycle."""

import sys
import time

import pytest
from typer.testing import CliRunner

from pswamp_tools import _proc, main
from pswamp_tools.commands import deploy


@pytest.mark.parametrize("command", [["deploy"], ["deploy", "minikube"], ["deploy", "logs"]], ids=" ".join)
def test_help_renders(command):
    result = CliRunner().invoke(main.app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


@pytest.mark.parametrize(("argv", "names"), [(["deploy", "minikube"], "minikube, kubectl"), (["deploy", "logs"], "kubectl")])
def test_missing_minikube_and_kubectl_are_named_with_install_hints(monkeypatch, capsys, argv, names):
    monkeypatch.setattr(_proc.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit) as caught:
        main.app(argv, prog_name="pswamp")
    assert caught.value.code == 1
    err = capsys.readouterr().err
    assert f"not found on PATH: {names}" in err
    assert "kubernetes.io/docs/tasks/tools" in err
    assert "Traceback" not in err


def test_a_build_that_says_it_failed_is_a_failure_despite_exit_0():
    assert deploy.build_failed("#5 DONE\nERROR: failed to solve: process did not complete\n")
    assert not deploy.build_failed("#5 DONE\nnaming to localhost/p-swamp:latest done\n")


def test_the_image_must_be_in_minikubes_store():
    assert deploy.image_present("docker.io/library/kafka:4\ndocker.io/library/p-swamp:latest\n")
    assert not deploy.image_present("docker.io/library/p-swamp:old\n")


def test_a_background_process_is_stopped_when_the_block_exits():
    with _proc.background([sys.executable, "-c", "import time; time.sleep(60)"]) as process:
        assert process.poll() is None
    assert process.poll() is not None


def test_a_background_process_is_stopped_when_the_block_raises():
    with pytest.raises(KeyboardInterrupt):
        with _proc.background([sys.executable, "-c", "import time; time.sleep(60)"]) as process:
            raise KeyboardInterrupt
    assert process.poll() is not None


def test_stopping_an_exited_process_is_a_no_op():
    with _proc.background([sys.executable, "-c", "pass"]) as process:
        deadline = time.monotonic() + 10
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
    assert process.returncode == 0
