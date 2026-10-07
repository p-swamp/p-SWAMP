"""``pswamp deps``: pull every dependency forward and report what moved (was update-dependencies.sh)."""

from __future__ import annotations

import enum
import os
import shutil
import stat
from pathlib import Path

import typer

from .. import _ui, deps_report
from .._paths import client_dir, repo_root
from .._proc import capture, require_tools, run

app = typer.Typer(
    help="Dependency maintenance: `deps update` pulls everything forward and reports what moved.",
    no_args_is_help=True,
)

# The workspace members' manifests: the fixed ones, plus every module project
# (modules/*/, one per module), found by glob so a new module needs no edit here.
FIXED_MEMBERS = [
    "pyproject.toml",
    "app/server-python/pyproject.toml",
    "models/pyproject.toml",
    "core/pyproject.toml",
    "tools/pyproject.toml",
]
MEMBER_GLOBS = ("modules/*/pyproject.toml",)


def workspace_manifests(root: Path) -> list[str]:
    found = sorted(path.relative_to(root).as_posix() for pattern in MEMBER_GLOBS for path in root.glob(pattern))
    return FIXED_MEMBERS + found


def manifests(root: Path) -> list[str]:
    """The manifests and lockfiles an update may rewrite: the "dirty" warning and
    the final diff both cover exactly these."""
    return [
        "app/client-web/package.json",
        "app/client-web/package-lock.json",
        "desktop/pyproject.toml",
        "desktop/uv.lock",
        "uv.lock",
        *workspace_manifests(root),
    ]


def locks(root: Path) -> list[tuple[str, str, list[str]]]:
    """(label, lockfile, manifests whose names count as direct dependencies)."""
    return [
        ("Desktop package", "desktop/uv.lock", ["desktop/pyproject.toml"]),
        ("Workspace", "uv.lock", workspace_manifests(root)),
        ("Web client", "app/client-web/package-lock.json", ["app/client-web/package.json"]),
    ]

# Pinned to a major so a future release can't shift behaviour under us.
NCU = "npm-check-updates@23"


class Target(str, enum.Enum):
    latest = "latest"
    minor = "minor"
    patch = "patch"


HELP = """\
Pull every dependency forward to the newest version its range allows, then report what moved.

It DECIDES nothing; it produces a candidate diff. Run it on a branch, read the
"What actually moved" report (a lockfile diff is ~95% sha256 hashes) and the
manifests, hard on any major jump, run the app, then open a PR. It edits the
manifests and the three lockfiles in place and nothing else. Needs the network.

[bold]Web client[/bold] (app/client-web)
  - npm-check-updates -u --peer ... rewrite package.json ranges to --target
    (--peer skips a bump no installed peer dependency accepts)
  - npm install ... re-resolve package-lock.json; on failure, once more from
    scratch (the existing lock can anchor npm to a tree it cannot reconcile)

[bold]Python[/bold]
  - uv lock --upgrade --project desktop ... desktop/uv.lock, FIRST
  - uv lock --upgrade ... the workspace's uv.lock; --upgrade implies --refresh,
    which is what makes uv re-read the p-swamp path dependency just upgraded

It does NOT widen a Python range (uv has no npm-check-updates): a cap like
`fastapi<0.116` needs a hand edit. The "Held back" section lists those, from
`uv tree --outdated --depth 1`. Then `pswamp check`, unless --no-check.
e2e/package-lock.json (Playwright) is not touched.
"""


def _force_remove(function, path, _exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except OSError:
        pass


def _npm_install(web: Path, report: _ui.Report) -> None:
    # `npm install`, not `npm ci`: ci installs the lockfile as is and would undo ncu.
    if run(["npm", "install"], cwd=web) == 0:
        _ui.ok("npm install (re-resolve package-lock.json)")
        return
    # Incremental first: a clean resolve re-picks every transitive package, so its
    # diff is far bigger than the upgrade. On failure, though, throw the lock away.
    _ui.console.print(
        "[yellow]  ! npm install failed against the existing lockfile — retrying from scratch[/yellow]\n"
        "    (deleting app/client-web/package-lock.json + node_modules; the lockfile\n"
        "     diff will be large because every transitive version is re-picked)"
    )
    shutil.rmtree(web / "node_modules", onerror=_force_remove)
    (web / "package-lock.json").unlink(missing_ok=True)
    if report.record("npm install (clean re-resolve of package-lock.json)", run(["npm", "install"], cwd=web) == 0):
        return
    # A conflict surviving a clean resolve is real: two bumps disagree.
    _ui.console.print(
        "[yellow]\n  Even a clean resolve failed, so two of the bumps genuinely disagree.\n"
        "  In order of preference:\n"
        "    1. re-run with --target minor — usually a major bump is what did it;\n"
        "    2. revert the one offending range by hand in app/client-web/package.json\n"
        "       (npm names both packages in the error) and re-run;\n"
        "    3. only then consider --legacy-peer-deps, and not from here —\n"
        "       it installs a tree npm itself considers broken.[/yellow]"
    )


def _held_back(label: str, *args: str) -> None:
    _ui.console.print(f"\n{label}:", markup=False)
    result = capture(["uv", "tree", "--outdated", "--depth", "1", *args], cwd=repo_root())
    if result.returncode != 0:
        _ui.console.print(
            f"  (uv tree failed — re-run `uv tree --outdated --depth 1 {' '.join(args)}` to see why)", markup=False
        )
        return
    rows = deps_report.held_back(result.stdout)
    if not rows:
        rows = ["  (nothing — every direct dependency is at the newest version published)"]
    for row in rows:
        _ui.console.print(row, markup=False)


@app.command(help=HELP)
def update(
    target: Target = typer.Option(
        Target.latest, "--target", envvar="TARGET", help="npm range target; `minor` for a no-surprises pass."
    ),
    no_check: bool = typer.Option(False, "--no-check", envvar="NO_CHECK", help="Skip `pswamp check` at the end."),
    verbose: bool = typer.Option(
        False, "--verbose", envvar="VERBOSE", help="List transitive version changes too, not just their counts."
    ),
) -> None:
    require_tools("node", "npm", "npx", "uv", "git", purpose="by pswamp deps update")
    root = repo_root()
    web = client_dir()
    report = _ui.Report()

    # A dirty manifest mixes your edits with this run's in the review diff. Warn
    # rather than refuse: bumping a cap by hand first is the way past a cap.
    dirty = capture(["git", "diff", "--name-only", "--", *manifests(root)], cwd=root).stdout.split()
    if dirty:
        _ui.console.print("[yellow]Note: these manifests already have uncommitted changes:[/yellow]")
        for name in dirty:
            _ui.info(name)
        _ui.console.print("[yellow]The diff below will mix them with this run's.[/yellow]")

    # Snapshot the lockfiles first: the report compares against these, not
    # HEAD, which is the wrong baseline when a lock was already dirty.
    before: dict[str, str | None] = {lock: deps_report.read_file(root / lock) for _, lock, _ in locks(root)}

    _ui.section(f"Web client (app/client-web) — target: {target.value}")
    report.step(
        "npm-check-updates (rewrite package.json ranges)",
        lambda: run(["npx", "--yes", NCU, "-u", "--peer", "--target", target.value], cwd=web),
    )
    _npm_install(web, report)

    _ui.section("Desktop package (desktop/)")
    # Locked FIRST, so the workspace below resolves against the result.
    report.step(
        "uv lock --upgrade (desktop: re-resolve desktop/uv.lock)",
        lambda: run(["uv", "lock", "--upgrade", "--project", "desktop"], cwd=root),
    )

    _ui.section("Workspace (root uv.lock: models, core, modules/*, tools, app/server-python)")
    report.step("uv lock --upgrade (workspace: re-resolve uv.lock)", lambda: run(["uv", "lock", "--upgrade"], cwd=root))

    _ui.section("Held back by a version range (needs a hand edit)")
    _held_back("Desktop (desktop/pyproject.toml)", "--project", "desktop")
    _held_back("Workspace (models, core, modules/*, tools, app/server-python)")
    # npm has no such gap (ncu rewrote the ranges), but a peer conflict can
    # still pin something below latest. `npm outdated` exits 1 for having output.
    _ui.console.print("\nWeb client (npm outdated — peer-dependency holdbacks):", markup=False)
    outdated = capture(["npm", "outdated"], cwd=web)
    for line in (outdated.stdout + outdated.stderr).splitlines():
        _ui.console.print(f"  {line}", markup=False)

    _ui.section("What actually moved")
    for label, lock, members in locks(root):
        _ui.console.print(f"\n{label} ({lock}):", markup=False)
        after = deps_report.read_file(root / lock)
        old = before[lock]
        if old is None or after is None:
            _ui.console.print("  (no before/after pair to compare)", markup=False)
            continue
        texts = [t for m in members if (t := deps_report.read_file(root / m)) is not None]
        for line in deps_report.version_delta(old, after, texts, lock.endswith(".json"), verbose):
            _ui.console.print(line, markup=False)

    _ui.section("Diff to review")
    run(["git", "--no-pager", "diff", "--stat", "--", *manifests(root)], cwd=root)
    _ui.console.print(
        "\nThe line counts above are mostly per-wheel hashes, not upgrades: read the\n"
        "list before them for that. What the lockfile diff IS good for is spotting a\n"
        "package that appeared without being asked for. The manifests are the\n"
        "decision and are small enough to read in full:\n"
        "  git --no-pager diff -- app/client-web/package.json '*pyproject.toml'",
        markup=False,
    )

    # Same gate as the pre-push hook and CI, in the upgraded environment
    # (`uv run` syncs it first). It does NOT run the app: a type-clean upgrade
    # can still break at runtime.
    if no_check:
        _ui.section("Skipping pswamp check (--no-check)")
    else:
        _ui.section("Running pswamp check")
        report.step("pswamp check", lambda: run(["uv", "run", "pswamp", "check"], cwd=root))

    _ui.section("Summary")
    if not report.failures:
        _ui.console.print("[green]Dependencies updated and checks passed.[/green]")
        _ui.console.print("Now: read the diff, run the app, then open a PR.")
        return
    _ui.console.print(f"[red]{len(report.failures)} step(s) failed:[/red]")
    for label in report.failures:
        _ui.console.print(f"  - {label}", markup=False)
    _ui.console.print(
        "\nThe working tree may hold a partial upgrade. `git checkout --` the manifests and\n"
        "lockfiles to start over, or fix the failure and re-run.",
        markup=False,
    )
    raise typer.Exit(1)
