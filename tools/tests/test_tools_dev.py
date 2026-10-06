"""``pswamp dev``: the healthz line filter, URL polling, and the compose command."""

import http.server
import socket
import subprocess
import sys
import threading
import time

import pytest
from typer.testing import CliRunner

from pswamp_tools import _net, _proc, main
from pswamp_tools._docker import Engine
from pswamp_tools.commands import dev


@pytest.mark.parametrize("command", [["dev"], ["dev", "server"], ["dev", "client"]], ids=" ".join)
def test_help_renders(command):
    result = CliRunner().invoke(main.app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_filtered_output_drops_the_healthz_lines_and_keeps_the_exit_code(capfd):
    script = (
        "import sys\n"
        "print('starting')\n"
        "print('INFO: 127.0.0.1 - \"GET /healthz HTTP/1.1\" 200 OK')\n"
        "print('error line', file=sys.stderr)\n"
        "sys.exit(3)\n"
    )
    code = _proc.run_filtered([sys.executable, "-c", script], drop=dev.HEALTHZ_LINE)
    out = capfd.readouterr().out
    assert code == 3
    assert "starting" in out and "error line" in out
    assert "healthz" not in out


def test_the_server_always_builds_and_watches_when_it_can():
    engine = Engine(name="docker", cli="docker", compose=("docker", "compose"))
    assert dev.server_command(engine, watch=True) == ["docker", "compose", "up", "--watch", "--build"]
    assert dev.server_command(engine, watch=False) == ["docker", "compose", "up", "--build"]


@pytest.mark.parametrize(("help_text", "expected"), [("  --watch  Watch source code", True), ("  --build", False)])
def test_watch_support_is_read_from_compose_up_help(monkeypatch, help_text, expected):
    result = subprocess.CompletedProcess([], 0, stdout=help_text, stderr="")
    monkeypatch.setattr(dev, "capture", lambda *a, **k: result)
    assert dev.supports_watch(Engine("podman", "podman", ("podman-compose",))) is expected


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_url_that_answers_is_up_and_a_refused_one_fails_fast():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert _net.answers(f"http://127.0.0.1:{server.server_port}/healthz")
    finally:
        server.shutdown()
        server.server_close()

    started = time.monotonic()
    assert not _net.wait_until_answers(f"http://127.0.0.1:{_free_port()}/", attempts=2, interval=0.01, dots=False)
    assert time.monotonic() - started < 5
