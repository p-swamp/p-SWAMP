"""Finding and running external tools, with a clear error when one is missing.

Every command resolves its tools through :func:`require_tool` before running
anything, so a missing ``npm`` is one sentence naming the tool and how to install
it, not a ``FileNotFoundError`` traceback halfway through a check. Resolution is
``shutil.which``, which on Windows also finds ``npm.cmd`` / ``npx.cmd`` through
``PATHEXT``; the resolved full path is what gets executed, so no shell is
involved (``shell=True`` is never used).

Python is never invoked as ``python3`` (on Windows that is often the Microsoft
Store stub): code that needs the CLI's own interpreter uses ``sys.executable``,
and code that needs the server's environment goes through ``uv run``.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

# How to get each tool the commands may need. Shown verbatim after "not found".
INSTALL_HINTS: dict[str, str] = {
    "uv": "install uv: https://docs.astral.sh/uv/getting-started/installation/",
    "node": "install Node.js 24 (https://nodejs.org/), which also provides npm and npx",
    "npm": "install Node.js 24 (https://nodejs.org/), which also provides npm and npx",
    "npx": "install Node.js 24 (https://nodejs.org/), which also provides npm and npx",
    "git": "install git: https://git-scm.com/downloads",
    "docker": "install Docker (https://docs.docker.com/get-docker/) or Podman (https://podman.io/)",
    "podman": "install Podman: https://podman.io/docs/installation",
    "minikube": "install minikube: https://minikube.sigs.k8s.io/docs/start/",
    "kubectl": "install kubectl: https://kubernetes.io/docs/tasks/tools/",
}


class ToolMissing(RuntimeError):
    """One or more required external tools are not on PATH."""

    def __init__(self, names: str | Sequence[str], hint: str | None = None, purpose: str | None = None):
        self.names = [names] if isinstance(names, str) else list(names)
        if hint is not None:
            self.hints = [hint]
        else:
            self.hints = list(dict.fromkeys(h for n in self.names if (h := INSTALL_HINTS.get(n))))
        noun = "tool" if len(self.names) == 1 else "tools"
        message = f"required {noun} not found on PATH: {', '.join(self.names)}"
        if purpose:
            message += f" (needed {purpose})"
        message += "".join(f"\n  -> {h}" for h in self.hints)
        super().__init__(message)


def _prepend_path(directory: Path) -> None:
    current = os.environ.get("PATH", "")
    if directory.is_dir() and str(directory) not in current.split(os.pathsep):
        os.environ["PATH"] = f"{directory}{os.pathsep}{current}"


def repair_path() -> None:
    """Re-add the usual uv and nvm locations to PATH.

    GUI git frontends (magit, IDEs) start hooks with a minimal PATH that lacks
    ``~/.local/bin`` (uv) and nvm's node directory, so a push that is fine from a
    terminal would otherwise fail with "uv: not found". The bash scripts made the
    same repair.
    """
    _prepend_path(Path.home() / ".local" / "bin")
    if shutil.which("npx") is None:
        versions = Path.home() / ".nvm" / "versions" / "node"
        if versions.is_dir():

            def version_key(path: Path) -> tuple[int, ...]:
                parts = path.name.lstrip("v").split(".")
                return tuple(int(p) if p.isdigit() else 0 for p in parts)

            installed = sorted((p for p in versions.iterdir() if (p / "bin").is_dir()), key=version_key)
            if installed:
                _prepend_path(installed[-1] / "bin")


def require_tool(name: str, hint: str | None = None, *, purpose: str | None = None) -> str:
    """The full path of ``name`` on PATH, or :class:`ToolMissing` with an install hint."""
    found = shutil.which(name)
    if found is None:
        raise ToolMissing(name, hint, purpose)
    return found


def require_tools(*names: str, purpose: str | None = None) -> dict[str, str]:
    """Resolve several tools at once, reporting every missing one in one error."""
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise ToolMissing(missing, purpose=purpose)
    return {name: require_tool(name) for name in names}


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment for a child process.

    * ``PYTHONUTF8=1``: a Python child writing ``✓`` into a pipe would otherwise
      encode it with the Windows ANSI code page and crash.
    * ``VIRTUAL_ENV`` dropped: uv ignores a foreign one anyway, with a warning on
      every call; the workspace's own ``.venv`` is always the one meant here.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env.pop("VIRTUAL_ENV", None)
    if extra:
        env.update(extra)
    return env


def _resolve(argv: Sequence[str]) -> list[str]:
    """``argv`` with its program resolved to a full path (``npx`` → ``…\\npx.cmd``)."""
    program, *rest = argv
    return [require_tool(program) if os.sep not in program and "/" not in program else program, *rest]


def run(
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    quiet: bool = False,
) -> int:
    """Run ``argv``, streaming its output (or swallowing it with ``quiet``); return its exit code.

    The program is resolved through :func:`require_tool`, so a missing one raises
    :class:`ToolMissing` rather than ``FileNotFoundError``. With ``quiet`` the
    output is captured and printed only if the command fails, so a failure is
    never silent.
    """
    resolved = _resolve(argv)
    kwargs: dict = {"cwd": cwd, "env": child_env(env)}
    if quiet:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    process = subprocess.Popen(resolved, **kwargs)
    try:
        output, _ = process.communicate()
    except KeyboardInterrupt:
        # The console delivered Ctrl-C to the child too; let it finish exiting.
        process.wait()
        return 130
    if quiet and process.returncode != 0 and output:
        sys.stdout.write(output.decode("utf-8", errors="replace"))
        sys.stdout.flush()
    return process.returncode


def run_filtered(
    argv: Sequence[str],
    *,
    drop: str,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run ``argv``, streaming its combined output minus every line containing ``drop``; its exit code.

    The port of ``cmd 2>&1 | grep -v --line-buffered …``, used to keep the
    /healthz probe lines out of a log view. Ctrl-C reaches the child too (same
    console), so on the first one the output keeps flowing while the child
    shuts down (``compose up`` stops its containers); a second one kills it.
    """
    process = subprocess.Popen(
        _resolve(argv), cwd=cwd, env=child_env(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    needle = drop.encode("utf-8")

    def pump() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            if needle not in raw:
                sys.stdout.write(raw.decode("utf-8", errors="replace"))
                sys.stdout.flush()

    try:
        pump()
        return process.wait()
    except KeyboardInterrupt:
        try:
            pump()
            process.wait()
        except KeyboardInterrupt:
            process.kill()
            process.wait()
        return 130


@contextlib.contextmanager
def background(
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> Iterator[subprocess.Popen]:
    """Run ``argv`` in the background (output discarded) for the ``with`` block, then stop it.

    The child gets its own process group (Windows) or session (POSIX), so a
    Ctrl-C in the console never reaches it directly: it is stopped here, on every
    exit path, by :func:`stop` -- the port of bash's ``&`` plus a ``kill`` trap.
    """
    kwargs: dict = {
        "cwd": cwd,
        "env": child_env(env),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(_resolve(argv), **kwargs)
    try:
        yield process
    finally:
        stop(process)


def stop(process: subprocess.Popen, timeout: float = 5.0) -> None:
    """Terminate ``process`` if it is still running, killing it if it does not exit in ``timeout``."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def capture(
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` and return its result with stdout/stderr as text (never raises on exit code)."""
    return subprocess.run(
        _resolve(argv),
        cwd=cwd,
        env=child_env(env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def uv_server(*args: str) -> list[str]:
    """``uv run --project app/server-python …``: a command in the server's locked env.

    Used for everything that needs the server's dependencies (FastAPI for the
    contract, websockets for the smoke clients, ruff and pytest from its dev
    group). Explicit rather than relying on the environment the CLI itself runs
    in, which depends on where ``uv run pswamp`` was started.
    """
    from ._paths import server_dir

    return ["uv", "run", "--project", str(server_dir()), *args]
