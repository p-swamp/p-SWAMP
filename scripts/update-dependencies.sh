#!/usr/bin/env bash
# Pull every dependency forward to the newest version its range allows, then hand
# you the diff to review. Staying near the head is cheap supply-chain defence — a
# boring monthly upgrade instead of one scary 400-package jump a year.
#
# It DECIDES nothing — it produces a candidate diff:
#   1. run on a branch,
#   2. read the "What actually moved" report (a lockfile diff is ~95% sha256
#      hashes; the report prints the versions), then the manifests, hard on any
#      major jump,
#   3. run the app and click through it,
#   4. open a PR, so someone else sees the same diff.
# It edits the manifests + three lockfiles in place and nothing else. Never
# commit the result unread — the reading is the whole point.
#
# WHAT IT TOUCHES
#   Web client (app/client-web)
#     - npm-check-updates -u   rewrite package.json ranges to newest (the step
#                              `npm update` won't do). --peer skips a bump no
#                              installed peerDependency accepts, and reports it.
#     - npm install            re-resolve package-lock.json; falls back to a
#                              from-scratch resolve on ERESOLVE (see that step).
#   Desktop package (desktop/) + the uv workspace (root uv.lock: core, modules,
#   app/server-python)
#     - uv lock --upgrade      re-resolve each closure. The workspace re-reads the
#                              p-swamp path dependency (--upgrade implies
#                              --refresh; a plain `uv lock` doesn't — see
#                              AGENTS.md), so it's locked AFTER the desktop.
#
# It does NOT widen a Python range: `uv lock --upgrade` respects pyproject.toml's
# bounds and uv has no npm-check-updates, so a cap like `fastapi>=…,<0.116` needs
# a hand edit. The report lists exactly which direct deps are held back and how
# far they could go.
#
# Env: TARGET=latest|minor|patch (npm range target, default latest; `minor` for a
# no-surprises pass), NO_CHECK=1 (skip error_check.sh), VERBOSE=1 (list transitive
# changes too). Needs the network — the one script here not reproducible offline.
set -uo pipefail

# Run from the repo root regardless of where the script is invoked from.
cd "$(dirname "$0")/.." || exit 1

TARGET="${TARGET:-latest}"

# GUI git frontends / IDEs launch with a minimal PATH missing ~/.local/bin (uv)
# and nvm's node dir. Re-add them (mirrors error_check.sh).
prepend_path() { case ":$PATH:" in *":$1:"*) ;; *) [ -d "$1" ] && PATH="$1:$PATH";; esac; }
prepend_path "$HOME/.local/bin"                  # uv
if ! command -v npx >/dev/null 2>&1; then         # node via nvm: newest installed
  newest_node_bin="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
  [ -n "$newest_node_bin" ] && prepend_path "$newest_node_bin"
fi
export PATH

missing=()
for tool in node npm npx uv git python3; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if [ "${#missing[@]}" -ne 0 ]; then
  printf '\033[31mupdate-dependencies: required tool(s) not found on PATH: %s\033[0m\n' "${missing[*]}"
  printf 'PATH=%s\n' "$PATH"
  exit 1
fi

# The manifests and lockfiles this script may rewrite, and the list it diffs at
# the end — a change outside these means something is wrong.
MANIFESTS=(
  app/client-web/package.json
  app/client-web/package-lock.json
  desktop/pyproject.toml
  desktop/uv.lock
  pyproject.toml
  uv.lock
  app/server-python/pyproject.toml
  core/pyproject.toml
  modules/pyproject.toml
)

# Snapshot the lockfiles before touching them, so the report can say what MOVED.
# A git diff can't be trusted: the locks may have been dirty at the start (see the
# warning below), making HEAD the wrong baseline.
BEFORE_DIR="$(mktemp -d)"
trap 'rm -rf "$BEFORE_DIR"' EXIT INT TERM
snapshot_before() {
  # snapshot_before <path> — stash a copy under a flattened name.
  [ -f "$1" ] && cp "$1" "$BEFORE_DIR/$(echo "$1" | tr / _)"
}
snapshot_before desktop/uv.lock
snapshot_before uv.lock
snapshot_before app/client-web/package-lock.json

FAILURES=()
section() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
step() {
  # step <label> <cmd...> — run one upgrade step, remember it if it fails. Steps
  # are independent (npm can succeed while PyPI is down), so the rest still run.
  local label="$1"; shift
  if "$@"; then
    printf '\033[32m  ✓ %s\033[0m\n' "$label"
  else
    printf '\033[31m  ✗ %s\033[0m\n' "$label"
    FAILURES+=("$label")
  fi
}

# A dirty manifest at the start mixes your edits with the script's in the review
# diff. Warn rather than refuse — bumping a cap by hand first is the documented way
# past a version cap, and you may want this run on top of it.
DIRTY="$(git diff --name-only -- "${MANIFESTS[@]}" 2>/dev/null)"
if [ -n "$DIRTY" ]; then
  printf '\033[33mNote: these manifests already have uncommitted changes:\033[0m\n'
  printf '  %s\n' $DIRTY
  printf '\033[33mThe diff below will mix them with this run'"'"'s.\033[0m\n'
fi

# --- Web client: package.json ranges, then the lockfile ---------------------
section "Web client (app/client-web) — target: $TARGET"

# ncu rewrites the RANGES in package.json (`npm update` only moves the lockfile
# within existing ranges, never past a ^18). Via npx, not a devDependency — it's a
# maintenance tool nothing in the build needs; pinned to a major so a future
# release can't shift behaviour under us; -u writes in place.
#
# --peer is not optional: without it ncu writes a version nothing else accepts
# (the first run bumped typescript past typescript-eslint's peer range, and every
# later step died on one ERESOLVE with no clue which of 22 bumps caused it). It
# reads INSTALLED peerDependencies, so it's only as current as node_modules — a
# second run after a big upgrade can move something further.
step "npm-check-updates (rewrite package.json ranges)" \
  bash -c "cd app/client-web && npx --yes npm-check-updates@23 -u --peer --target '$TARGET'"

# Re-resolve against the rewritten ranges. `npm install`, not `npm ci` — ci
# installs the lockfile as-is and would undo the above.
#
# Two attempts, and the second isn't paranoia: npm resolves incrementally against
# the existing lock, which can anchor the tree to a version the new ranges can't
# reconcile even with node_modules deleted (seen for real: @vitejs/plugin-react
# died on ERESOLVE over @babel/core via optional peers, while the same
# package.json resolved cleanly in an empty dir). So on failure, throw the lock
# away and resolve from scratch. Incremental FIRST, though: a clean resolve
# re-picks every transitive package, so its diff is far bigger than the upgrade.
NPM_INSTALL_OK=1
if ( cd app/client-web && npm install ); then
  printf '\033[32m  ✓ npm install (re-resolve package-lock.json)\033[0m\n'
else
  printf '\033[33m  ! npm install failed against the existing lockfile — retrying from scratch\033[0m\n'
  printf '    (deleting app/client-web/package-lock.json + node_modules; the lockfile\n'
  printf '     diff will be large because every transitive version is re-picked)\n'
  if ( cd app/client-web && rm -rf node_modules package-lock.json && npm install ); then
    printf '\033[32m  ✓ npm install (clean re-resolve of package-lock.json)\033[0m\n'
  else
    printf '\033[31m  ✗ npm install (re-resolve package-lock.json)\033[0m\n'
    FAILURES+=("npm install (re-resolve package-lock.json)")
    NPM_INSTALL_OK=0
  fi
fi

# A conflict surviving a clean resolve is real — two bumps disagree. npm's
# ERESOLVE names both packages but not the way out, so spell it out.
if [ "$NPM_INSTALL_OK" -eq 0 ]; then
  printf '\033[33m\n  Even a clean resolve failed, so two of the bumps genuinely disagree.\n'
  printf '  In order of preference:\n'
  printf '    1. re-run with TARGET=minor — usually a major bump is what did it;\n'
  printf '    2. revert the one offending range by hand in app/client-web/package.json\n'
  printf '       (npm names both packages in the error) and re-run this script;\n'
  printf '    3. only then consider --legacy-peer-deps, and not from this script —\n'
  printf '       it installs a tree npm itself considers broken.\n\033[0m'
fi

# --- Desktop package in desktop/ --------------------------------------------
section "Desktop package (desktop/)"

# The desktop package, with its own desktop/uv.lock outside the workspace — and,
# since the merge, the analysis core the web backend imports, so it ships in the
# image too. Its ranges are
# mostly open (`numpy>=2.2.5`), so --upgrade reaches latest; the exact pins
# (PySide6==6.8.3) and git deps stay put. Locked FIRST, so the backend below
# resolves against the result.
step "uv lock --upgrade (desktop: re-resolve desktop/uv.lock)" \
  uv lock --upgrade --project desktop

# --- The uv workspace (core, modules, web backend) ---------------------------
section "Workspace (root uv.lock: core, modules, app/server-python)"

# --upgrade implies --refresh, which is what makes uv re-read the p-swamp path
# dependency. A plain `uv lock` would print "Resolved N packages" and ignore the
# desktop manifest we just changed — the AGENTS.md trap, and why the two are
# locked in this order.
step "uv lock --upgrade (workspace: re-resolve uv.lock)" \
  uv lock --upgrade

# --- What is still held back ------------------------------------------------
section "Held back by a version range (needs a hand edit)"

# Everything reachable is taken. What `uv tree --outdated` still flags is a DIRECT
# dependency whose own pyproject.toml constraint blocks it — the Python gap this
# script can't close, since uv has no npm-check-updates. Depth 1 on purpose: a
# transitive holdback isn't actionable here (drop --depth to see it anyway).
held_back() {
  # held_back <label> [uv args...] — print only the rows uv marks "(latest: …)".
  # `uv tree --outdated` prints the WHOLE tree, so without this filter the section
  # lists all 30 direct deps and buries the three held back.
  local label="$1"; shift
  local out rc
  out="$(uv tree --outdated --depth 1 "$@" 2>/dev/null)"; rc=$?
  printf '\n%s:\n' "$label"
  if [ "$rc" -ne 0 ]; then
    printf '  (uv tree failed — re-run `uv tree --outdated --depth 1 %s` to see why)\n' "$*"
    return
  fi
  out="$(printf '%s\n' "$out" | grep '(latest:')"
  if [ -z "$out" ]; then
    printf '  (nothing — every direct dependency is at the newest version published)\n'
  else
    # Strip the tree glyphs; with most rows filtered out they connect nothing.
    printf '%s\n' "$out" | sed -E 's/^[^A-Za-z0-9@_]*/  /'
  fi
}

held_back "Desktop (desktop/pyproject.toml)" --project desktop
held_back "Workspace (core, modules, app/server-python)"

# npm has no equivalent gap — ncu just rewrote the ranges — but a peer
# dependency conflict can still pin something below latest, and that shows up
# here. `npm outdated` exits non-zero merely for having output, hence the `|| true`.
printf '\nWeb client (npm outdated — peer-dependency holdbacks):\n'
( cd app/client-web && npm outdated ) 2>&1 | sed 's/^/  /' || true

# --- What actually moved ----------------------------------------------------
section "What actually moved"

# A lockfile diff is a terrible upgrade summary: ~95% of its changed lines are
# sha256 hashes (measured: 1773 changed lines in root uv.lock, 1521 of them hashes,
# 72 actual `version =`). So parse the before/after pairs and print the versions —
# this, not the diff, is what to read first.
version_delta() {
  # version_delta <label> <lockfile> <manifest>... — compare snapshot vs now,
  # splitting DIRECT dependencies (named in the manifest, yours) from transitive
  # ones (your deps' choices). The split is what makes it readable — one radix-ui
  # bump drags ~70 packages with it. VERBOSE=1 prints the transitive detail too.
  local label="$1" path="$2"
  local before="$BEFORE_DIR/$(echo "$path" | tr / _)"
  printf '\n%s (%s):\n' "$label" "$path"
  if [ ! -f "$before" ] || [ ! -f "$path" ]; then
    printf '  (no before/after pair to compare)\n'
    return
  fi
  VERBOSE="${VERBOSE:-}" python3 - "$before" "$path" "${@:3}" <<'PYEOF'
import json, os, re, sys

def read_lock(path):
    """name -> comma-joined set of versions. A package can be resolved at two
    versions at once: uv forks a resolution when requires-python spans a
    boundary (numpy 2.4.6 for <3.12, 2.5.2 for >=3.12), and npm nests a second
    copy when two dependents disagree."""
    text = open(path, encoding="utf-8").read()
    out = {}
    if path.endswith(".json"):
        # npm: every entry under `packages`, keyed by the last node_modules/
        # segment so a nested copy collapses onto the same name.
        for key, meta in (json.loads(text).get("packages") or {}).items():
            if not key or "version" not in meta:
                continue          # the "" root entry, plus link/workspace stubs
            out.setdefault(key.rsplit("node_modules/", 1)[-1], set()).add(meta["version"])
    else:
        # uv.lock: TOML, but only two fields per [[package]] block are wanted,
        # so a regex avoids needing a TOML parser at all.
        for block in text.split("[[package]]")[1:]:
            n = re.search(r'^name = "(.*)"$', block, re.M)
            v = re.search(r'^version = "(.*)"$', block, re.M)
            if n and v:
                out.setdefault(n.group(1), set()).add(v.group(1))
    return {k: ", ".join(sorted(v)) for k, v in out.items()}

def read_direct(path):
    """The names the manifest itself asks for — everything else is transitive."""
    if path.endswith(".json"):
        m = json.load(open(path, encoding="utf-8"))
        names = set()
        for field in ("dependencies", "devDependencies", "optionalDependencies"):
            names |= set(m.get(field) or {})
        return names
    # pyproject.toml. tomllib is 3.11+, which this project requires anyway, but
    # the report is a nicety and must not take the script down on an older
    # interpreter — hence the regex fallback.
    text = open(path, encoding="utf-8").read()
    try:
        import tomllib
        data = tomllib.loads(text)
        reqs = list(data.get("project", {}).get("dependencies", []))
        for group in (data.get("project", {}).get("optional-dependencies") or {}).values():
            reqs += group
        for group in (data.get("dependency-groups") or {}).values():
            reqs += [r for r in group if isinstance(r, str)]
    except Exception:
        reqs = re.findall(r'^\s*"([^"]+)"\s*,?\s*$', text, re.M)
    # Strip extras and any version/url specifier, then normalise the way PyPI
    # does (case-insensitive, - and _ equivalent) so these match the lock's keys.
    out = set()
    for req in reqs:
        name = re.split(r"[\s\[<>=!~;@]", req.strip(), maxsplit=1)[0]
        if name:
            out.add(name.lower().replace("_", "-"))
    return out

before, after = read_lock(sys.argv[1]), read_lock(sys.argv[2])
direct = set().union(*(read_direct(m) for m in sys.argv[3:]))

def classify(names):
    return sorted(n for n in names if n in direct), sorted(n for n in names if n not in direct)

changed = {k for k in before.keys() & after.keys() if before[k] != after[k]}
added   = after.keys() - before.keys()
removed = before.keys() - after.keys()

if not (changed or added or removed):
    print("  (nothing moved — everything was already at the newest version its range allows)")
    raise SystemExit

verbose = os.environ.get("VERBOSE") == "1"
for kind, names, fmt in (
    ("changed", changed, lambda n: f"{before[n]} -> {after[n]}"),
    ("added",   added,   lambda n: f"added {after[n]}"),
    ("removed", removed, lambda n: f"removed (was {before[n]})"),
):
    d, _ = classify(names)
    for name in d:
        print(f"  {name:<34} {fmt(name)}")

t_changed, t_added, t_removed = (classify(x)[1] for x in (changed, added, removed))
if verbose:
    for names, fmt in ((t_changed, lambda n: f"{before[n]} -> {after[n]}"),
                       (t_added,   lambda n: f"added {after[n]}"),
                       (t_removed, lambda n: f"removed (was {before[n]})")):
        for name in names:
            print(f"    (transitive) {name:<22} {fmt(name)}")

d_changed, d_added, d_removed = (classify(x)[0] for x in (changed, added, removed))
print(f"\n  direct:     {len(d_changed)} upgraded, {len(d_added)} added, {len(d_removed)} removed")
print(f"  transitive: {len(t_changed)} upgraded, {len(t_added)} added, {len(t_removed)} removed"
      + ("" if verbose else "   (VERBOSE=1 to list)"))
PYEOF
}

version_delta "Desktop package" desktop/uv.lock                  desktop/pyproject.toml
version_delta "Workspace"       uv.lock                          app/server-python/pyproject.toml core/pyproject.toml modules/pyproject.toml
version_delta "Web client"      app/client-web/package-lock.json app/client-web/package.json

# --- The diff to review -----------------------------------------------------
section "Diff to review"
git --no-pager diff --stat -- "${MANIFESTS[@]}"
printf '\nThe line counts above are mostly per-wheel hashes, not upgrades — read the\n'
printf 'list before them for that. What the lockfile diff IS good for is spotting a\n'
printf 'package that appeared without being asked for. The manifests are the\n'
printf 'decision and are small enough to read in full:\n'
printf '  git --no-pager diff -- app/client-web/package.json desktop/pyproject.toml app/server-python/pyproject.toml core/pyproject.toml modules/pyproject.toml\n'

# --- Does it still hold together? -------------------------------------------
# The upgrade is half the job; the other half is finding what it broke. Same gate
# as the pre-push hook and CI. It does NOT run the app — a type-clean upgrade can
# still break at runtime (that's step 3 in the header).
if [ "${NO_CHECK:-}" = "1" ]; then
  section "Skipping error_check.sh (NO_CHECK=1)"
else
  section "Running scripts/error_check.sh"
  ./scripts/error_check.sh || FAILURES+=("error_check.sh")
fi

# --- Summary ----------------------------------------------------------------
section "Summary"
if [ "${#FAILURES[@]}" -eq 0 ]; then
  printf '\033[32mDependencies updated and checks passed.\033[0m\n'
  printf 'Now: read the diff, run the app, then open a PR.\n'
  exit 0
fi
printf '\033[31m%d step(s) failed:\033[0m\n' "${#FAILURES[@]}"
printf '  - %s\n' "${FAILURES[@]}"
printf '\nThe working tree may hold a partial upgrade. `git checkout --` the\n'
printf 'manifests and lockfiles to start over, or fix the failure and re-run.\n'
exit 1
