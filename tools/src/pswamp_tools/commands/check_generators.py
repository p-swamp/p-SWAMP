"""``pswamp check-generators``: prove both generators still produce working apps (was check-generators.sh)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import typer

from .. import _ui, generate
from .._paths import repo_root
from .._proc import capture, require_tools, run

COUNTER = "check-counter"
MODULE = "check-module"
# Above this, a temp root plus a worktree's deepest path (node_modules aside, which
# is linked, not copied) risks Windows' 260-char limit even with core.longpaths,
# because not every tool (npm, tsc) honours it.
MAX_TEMP_ROOT = 48

HELP = """\
Prove both generators still produce working apps, without touching this working tree.

In a throwaway git worktree holding a snapshot of this working tree (committed
or not, untracked files included):

  1. `pswamp new subapp` (a counter) and `pswamp new module` (a module and its page);
  2. `pswamp check` over the result;
  3. the generated module's tests (its own tests/ folder, its page's socket in
     the server's tests/), and the layering test over the result;
  4. import the module-worker's pipelines and modules as patched into
     docker-compose.yml and k8s/p-swamp-local.yaml, from outside the server
     tree, as a worker does.

Slow: the worktree gets its own uv environment. app/client-web/node_modules is
linked in (a directory junction on Windows) rather than reinstalled; without one
`pswamp check` runs `npm ci` there. The worktree is removed on every exit path.
"""

# Step 4, run in the worktree's server environment from modules/ (outside the
# server tree, as a worker runs). argv: module slug, then a JSON file of {path: pattern}.
WORKER_CHECK = """\
import json, re, sys
from pathlib import Path
from pswamp_core.worker import load_pipelines

module, patterns = sys.argv[1], json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
for path, pattern in patterns.items():
    text = (Path("..") / path).read_text(encoding="utf-8").replace("\\r\\n", "\\n")
    lists = {var: re.search(pattern.format(var=var), text, re.M).group(1)
             for var in ("PSWAMP_WORKER_PIPELINES", "PSWAMP_WORKER_MODULES")}
    names = set(lists["PSWAMP_WORKER_MODULES"].split(","))
    hosted = [m.name for p in load_pipelines(lists["PSWAMP_WORKER_PIPELINES"]) for m in p.modules if m.name in names]
    assert module in hosted, f"{path}: {hosted}"
    print(f"    {path}: {', '.join(hosted)}")
"""


def short_temp_root() -> Path:
    """A temp dir short enough for a worktree on Windows (the default can be deeply nested)."""
    default = Path(tempfile.gettempdir())
    if len(str(default)) <= MAX_TEMP_ROOT:
        return default
    fallback = Path.home() / ".pswamp-tmp"
    fallback.mkdir(exist_ok=True)
    return fallback


def is_link(path: Path) -> bool:
    """A symlink, or (on Windows) a directory junction."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return getattr(info, "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)


def link_dir(target: Path, link: Path) -> bool:
    """Point ``link`` at the directory ``target``: a junction on Windows (no admin
    rights or developer mode needed, unlike a symlink), a symlink elsewhere. False if neither works."""
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except OSError:
        return False
    return True


def unlink_dir(link: Path) -> None:
    """Remove a link made by :func:`link_dir`, never what it points at."""
    if not is_link(link):
        return
    if sys.platform == "win32":
        os.rmdir(link)  # removes the junction itself
    else:
        link.unlink()


def _force_remove(function, path, _exc_info) -> None:
    # Windows refuses to delete read-only files (git objects, some venv files).
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except OSError:
        pass


def copy_untracked(repo: Path, tree: Path) -> int:
    """Copy every untracked, not-ignored file of ``repo`` into ``tree``; the count."""
    listed = capture(["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=repo)
    if listed.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {listed.stderr.strip()}")
    count = 0
    for name in filter(None, listed.stdout.split("\0")):
        source = repo / name
        if not source.is_file():
            continue
        dest = tree / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        count += 1
    return count


def snapshot(repo: Path, tree: Path) -> None:
    """A detached worktree at ``tree`` holding ``repo``'s working tree as it is now; nothing is stashed."""
    identity = {
        "GIT_AUTHOR_NAME": "check",
        "GIT_AUTHOR_EMAIL": "check@localhost",
        "GIT_COMMITTER_NAME": "check",
        "GIT_COMMITTER_EMAIL": "check@localhost",
    }
    # A commit object of the tracked files as they are now; empty when the tree is clean.
    created = capture(["git", "stash", "create"], cwd=repo, env=identity)
    rev = created.stdout.strip() if created.returncode == 0 and created.stdout.strip() else "HEAD"
    code = run(
        ["git", "-c", "core.longpaths=true", "worktree", "add", "--detach", "--quiet", str(tree), rev],
        cwd=repo,
    )
    if code != 0:
        raise RuntimeError("git worktree add failed")
    _ui.info(f"untracked files copied: {copy_untracked(repo, tree)}")


def cleanup(repo: Path, work: Path, tree: Path) -> None:
    # The link first, so removing the worktree never reaches the real node_modules.
    node_modules = tree / "app" / "client-web" / "node_modules"
    try:
        unlink_dir(node_modules)
    except OSError as exc:
        _ui.error(f"could not remove the node_modules link {node_modules} ({exc}); leaving {work} in place")
        return
    if is_link(node_modules):
        _ui.error(f"the node_modules link {node_modules} is still there; leaving {work} in place")
        return
    run(["git", "worktree", "remove", "--force", str(tree)], cwd=repo, quiet=True)
    shutil.rmtree(work, onerror=_force_remove)
    run(["git", "worktree", "prune"], cwd=repo, quiet=True)
    if work.exists():
        _ui.info(f"(could not delete everything under {work}; remove it by hand)")


def check_generators() -> None:
    require_tools("git", "uv", purpose="by pswamp check-generators")
    repo = repo_root()
    work = Path(tempfile.mkdtemp(prefix="pswamp-gen-", dir=short_temp_root()))
    tree = work / "tree"
    module_pkg = MODULE.replace("-", "_")
    # The worktree's own uv environment: copied, not hardlinked, from the uv cache.
    # A throwaway env gains nothing from links, and hardlinking fails outright on
    # some Windows setups (os error 396 when the cache is under a cloud-synced profile).
    env = {"UV_LINK_MODE": os.environ.get("UV_LINK_MODE", "copy")}

    def step(title: str, argv: list[str], cwd: Path) -> None:
        _ui.section(title)
        if run(argv, cwd=cwd, env=env) != 0:
            _ui.error(f"{title}: failed")
            raise typer.Exit(1)

    try:
        _ui.section(f"Snapshot this working tree into {tree}")
        snapshot(repo, tree)
        real_modules = repo / "app" / "client-web" / "node_modules"
        if real_modules.is_dir():
            linked = link_dir(real_modules, tree / "app" / "client-web" / "node_modules")
            _ui.info("node_modules: linked" if linked else "node_modules: could not link; `pswamp check` will npm ci")

        _ui.section("Generate a counter subapp and a module app")
        for kind, slug, label in (("subapp", COUNTER, "Check counter"), ("module", MODULE, "Check module")):
            if run(["uv", "run", "pswamp", "new", kind, slug, label, "--no-check"], cwd=tree, env=env) != 0:
                _ui.error(f"pswamp new {kind} failed")
                raise typer.Exit(1)

        step("Static checks over the generated tree", ["uv", "run", "pswamp", "check"], tree)
        step(
            "The generated module's tests",
            [
                "uv", "run", "pswamp", "test", "server", "-q",
                f"tests/test_{module_pkg}.py",
                f"../../modules/pswamp_modules/{module_pkg}/tests",
                "../../modules/pswamp_modules/tests/test_layering.py",
                "../../models/tests/test_models_layering.py",
            ],
            tree,
        )
        # The script and its patterns go through files, not the command line,
        # whose quoting differs between Windows and POSIX.
        patterns = {path.as_posix(): pattern for path, pattern in generate.WORKER_LIST_PATTERNS.items()}
        (work / "worker_check.py").write_text(WORKER_CHECK, encoding="utf-8")
        (work / "patterns.json").write_text(json.dumps(patterns), encoding="utf-8")
        step(
            "The module-worker hosts it, as patched",
            [
                "uv", "run", "--project", "../app/server-python", "python",
                str(work / "worker_check.py"), MODULE, str(work / "patterns.json"),
            ],
            tree / "modules",
        )
    except typer.Exit:
        raise
    except (RuntimeError, subprocess.SubprocessError) as exc:
        _ui.error(str(exc))
        raise typer.Exit(1) from None
    finally:
        _ui.section("Remove the worktree")
        cleanup(repo, work, tree)

    _ui.console.print("\n[green]Both generators produce working apps.[/green]")
