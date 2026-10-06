"""What a dependency upgrade actually moved, read from the lockfiles rather than their diff.

A lockfile diff is a terrible upgrade summary: ~95% of its changed lines are
sha256 hashes (measured: 1773 changed lines in uv.lock, 1521 of them hashes, 72
actual ``version =``). So the before/after pairs are parsed and the versions
printed, direct dependencies (named in a manifest: yours) apart from transitive
ones (your dependencies' choices), since one radix-ui bump drags ~70 packages
with it.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


def _norm(name: str) -> str:
    # Case-insensitive, `-` and `_` equivalent: how PyPI (and uv.lock) spell names.
    return name.lower().replace("_", "-")


def read_lock(text: str, is_npm: bool) -> dict[str, str]:
    """name -> comma-joined sorted versions.

    A package can be resolved at two versions at once: uv forks a resolution when
    requires-python spans a boundary, and npm nests a second copy when two
    dependents disagree.
    """
    found: dict[str, set[str]] = {}
    if is_npm:
        # Every entry under `packages`, keyed by the last node_modules/ segment so
        # a nested copy collapses onto the same name; skip the "" root and links.
        for key, meta in (json.loads(text).get("packages") or {}).items():
            if not key or "version" not in meta:
                continue
            found.setdefault(key.rsplit("node_modules/", 1)[-1], set()).add(meta["version"])
    else:
        # uv.lock is TOML, but only two fields per [[package]] are wanted.
        for block in text.split("[[package]]")[1:]:
            name = re.search(r'^name = "(.*)"$', block, re.M)
            version = re.search(r'^version = "(.*)"$', block, re.M)
            if name and version:
                found.setdefault(name.group(1), set()).add(version.group(1))
    return {name: ", ".join(sorted(versions)) for name, versions in found.items()}


def read_direct(text: str, is_npm: bool) -> set[str]:
    """The names a manifest itself asks for (package.json or pyproject.toml)."""
    if is_npm:
        data = json.loads(text)
        names: set[str] = set()
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            names |= set(data.get(section) or {})
        return names
    data = tomllib.loads(text)
    project = data.get("project", {})
    requirements = list(project.get("dependencies", []))
    for group in (project.get("optional-dependencies") or {}).values():
        requirements += group
    for group in (data.get("dependency-groups") or {}).values():
        requirements += [r for r in group if isinstance(r, str)]
    out = set()
    for requirement in requirements:
        name = re.split(r"[\s\[<>=!~;@]", requirement.strip(), maxsplit=1)[0]
        if name:
            out.add(_norm(name))
    return out


def version_delta(before: str, after: str, manifests: list[str], is_npm: bool, verbose: bool = False) -> list[str]:
    """The report lines for one lockfile: direct changes listed, transitive ones counted (or listed)."""
    old, new = read_lock(before, is_npm), read_lock(after, is_npm)
    direct: set[str] = set().union(*(read_direct(m, is_npm) for m in manifests)) if manifests else set()

    def is_direct(name: str) -> bool:
        return name in direct or _norm(name) in direct

    changed = {n for n in old.keys() & new.keys() if old[n] != new[n]}
    added = new.keys() - old.keys()
    removed = old.keys() - new.keys()
    if not (changed or added or removed):
        return ["  (nothing moved — everything was already at the newest version its range allows)"]

    kinds = (
        (changed, lambda n: f"{old[n]} -> {new[n]}"),
        (added, lambda n: f"added {new[n]}"),
        (removed, lambda n: f"removed (was {old[n]})"),
    )
    lines: list[str] = []
    for names, describe in kinds:
        lines += [f"  {n:<34} {describe(n)}" for n in sorted(names) if is_direct(n)]
    if verbose:
        for names, describe in kinds:
            lines += [f"    (transitive) {n:<22} {describe(n)}" for n in sorted(names) if not is_direct(n)]

    def count(names: set[str], want_direct: bool) -> int:
        return sum(1 for n in names if is_direct(n) == want_direct)

    lines.append("")
    lines.append(
        f"  direct:     {count(changed, True)} upgraded, {count(added, True)} added, {count(removed, True)} removed"
    )
    lines.append(
        f"  transitive: {count(changed, False)} upgraded, {count(added, False)} added, "
        f"{count(removed, False)} removed" + ("" if verbose else "   (--verbose to list)")
    )
    return lines


def held_back(tree_output: str) -> list[str]:
    """The rows of ``uv tree --outdated --depth 1`` that uv marks ``(latest: …)``, glyphs stripped.

    `uv tree --outdated` prints the whole tree, so without this filter the
    section would list every direct dependency and bury the few held back.
    """
    return [re.sub(r"^[^A-Za-z0-9@_]*", "  ", line) for line in tree_output.splitlines() if "(latest:" in line]


def read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
