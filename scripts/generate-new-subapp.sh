#!/usr/bin/env bash
# Scaffold a new subapp — a page and its api — wired into the nav, the route
# table, the ws path table and the backend APPS registry (every step in AGENTS.md's
# "Adding a page" / "Adding a backend api").
#
#   scripts/generate-new-subapp.sh grid-overview "Grid Overview"
#
# What comes out already works: a nav entry, a page at /grid-overview, a WebSocket
# pushing state from a new backend package, and two POST commands over a per-client
# counter. Replacing that counter is the only work left.
#
# Generated files come from scripts/templates/<set>/ — edit those, not this
# script, to change what a subapp starts life as. Each is <filename>.template;
# the suffix is stripped on render and keeps editors off them.
#
# TEMPLATE_SET picks the set: `subapp` (the default: the counter above) or
# `module` (a module over the core pipeline and the page that shows it, which is
# what generate-new-module-with-frontend.sh runs).
#
# The subapp joins the api contract with no registry entry (its package exports
# WS_MESSAGE, api_contract.py collects it); this script regenerates both artifacts
# at the end. Commit them with the rest. NO_CHECK=1 skips the error_check.sh run.
set -euo pipefail

# Run from the repo root regardless of where the script is invoked from.
cd "$(dirname "$0")/.."

GENERATOR="${GENERATOR:-scripts/generate-new-subapp.sh}"
if [ $# -ne 2 ]; then
  echo "usage: $GENERATOR <url-name> \"<Nav Label>\"" >&2
  echo "   eg: $GENERATOR grid-overview \"Grid Overview\"" >&2
  exit 1
fi

# python3 does the work: derive the name's spellings, render the templates, and
# insert into the registries by anchor. (Already required by error_check.sh.)
SLUG="$1" LABEL="$2" TEMPLATE_SET="${TEMPLATE_SET:-subapp}" python3 - <<'PY'
import json
import keyword
import os
import re
import shutil
import sys
from pathlib import Path


def die(msg):
    print(f"\033[31m{msg}\033[0m", file=sys.stderr)
    sys.exit(1)


# The name shows up in five shapes; keeping them in step by hand is what this
# script removes. Templates spell them __SLUG__, __PKG__ … __LABEL__.
#
#   slug            grid-overview          URL, page folder, /api prefix
#   pkg             grid_overview          Python package (must be an identifier)
#   name            GridOverview           React component, hook, model class
#   ws_path_const   GRID_OVERVIEW_WS_PATH  ws path const in lib/servers.ts
#   api_path_const  GRID_OVERVIEW_API_PATH REST prefix const, same file
#   upper           GRID_OVERVIEW          environment variable prefix (module set)
#
# Two path consts because the directions use two transports: state down the
# socket, commands up as POSTs (see AGENTS.md).

slug = os.environ["SLUG"]
label = os.environ["LABEL"]
template_set = os.environ["TEMPLATE_SET"]
if template_set not in ("subapp", "module"):
    die(f"TEMPLATE_SET={template_set!r}: use 'subapp' or 'module'.")
pkg = slug.replace("-", "_")
name = "".join(word.capitalize() for word in slug.split("-"))
ws_path_const = f"{pkg.upper()}_WS_PATH"
api_path_const = f"{pkg.upper()}_API_PATH"

# The 32-char cap keeps the rendered Python lines short and readable. (They used
# to have to fit ruff's 88-column limit; error_check.sh no longer enforces line
# length — formatting and pycodestyle were dropped from the gate.)
if (
    not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", slug)
    or len(slug) > 32
    or keyword.iskeyword(pkg)
):
    die(f"{slug!r} is not usable: give lowercase words joined by hyphens, max 32 chars.")

# The label is free text a person types, and it lands in six places: a single-quoted
# TS string (the nav entry), a double-quoted Python string (the AppEntry
# description), two Python docstrings, a JSX text node and two JS comments. The two
# code-string sites are escaped when written (py_str / ts_squote below). The four
# prose sites a blind token substitution cannot escape, so reject the handful of
# characters that would break *them* — angle brackets and braces (JSX), a backtick
# or backslash, and the comment (`*/`) / docstring (`\"\"\"`) terminators — rather
# than emit a subapp that will not compile. Everyday punctuation stays allowed:
# "Operator's View" is a perfectly good label, and used to produce broken TypeScript.
if (
    not label.strip()
    or len(label) > 48
    or set(label) & set("<>{}\\`")
    or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in label)
    or "*/" in label
    or '"""' in label
):
    die(
        f"{label!r} is not usable as a nav label: give a short human phrase "
        "(max 48 chars) without angle brackets, braces, backslashes, backticks "
        "or control characters."
    )


def py_str(value):
    """`value` as a Python string literal. JSON strings are a subset of Python's,
    so json.dumps escapes quotes and backslashes correctly for this use."""
    return json.dumps(value)


def ts_squote(value):
    """`value` as a single-quoted TS/JS string literal, matching the style already
    in servers.ts and AppLayout.tsx. Validation rules a backslash out, but escape
    it too so this stays correct if that ever loosens."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


WEB = Path("app/client-web/src")
PY_SRC = Path("app/server-python/src")
page_dir = WEB / "pages" / slug
api_dir = PY_SRC / pkg

if page_dir.exists() or api_dir.exists():
    die(f"{slug} already exists as a page or an api package — pick another name.")


# --- render scripts/templates/ into the two new folders ---------------------
#
# File *names* carry the tokens too (use__NAME__Socket.ts.template), so a template
# folder maps 1:1 onto the subapp. Every template ends in .template, stripped here.
# The suffix keeps editors and type-checkers off them — a real `.ts` holding
# `__WS_PATH_CONST__` would be a wall of IDE errors on a non-source file. A missing
# suffix is an error, not a no-op, so the convention can't rot into "some of them".


def render(text):
    for token, value in (
        ("__SLUG__", slug),
        ("__PKG__", pkg),
        ("__NAME__", name),
        ("__WS_PATH_CONST__", ws_path_const),
        ("__API_PATH_CONST__", api_path_const),
        ("__UPPER__", pkg.upper()),
        ("__LABEL__", label),
    ):
        text = text.replace(token, value)
    return text


TEMPLATES = Path("scripts/templates") / template_set
sources = [
    (TEMPLATES / "server-python", api_dir),
    (TEMPLATES / "client-web", page_dir),
]
if template_set == "module":  # its unit tests go into the server's tests/
    sources.append((TEMPLATES / "tests", Path("app/server-python/tests")))

# Validate every template's name before rendering. This, the slug/label checks
# above and the anchor checks below all run before the commit phase touches the
# working tree, so any of them can die() with nothing half-written.
for templates, _ in sources:
    if not templates.is_dir():
        die(f"Missing {templates}/ — the templates live beside this script.")
    for template in sorted(templates.iterdir()):
        if not template.name.endswith(".template"):
            die(f"{template} must be named <filename>.template — see the note above.")

# Everything below computes the whole change set — every rendered file and every
# registry patch — in memory first, and only then touches the working tree. So a
# missing anchor (or any other failure) aborts with nothing written, instead of
# the old behaviour: folders and half the registries on disk, no rollback, and a
# re-run blocked by "already exists".

# --- render scripts/templates/ into the two new folders (in memory) ---------

rendered = {}  # dest Path -> file contents
for templates, dest_dir in sources:
    for template in sorted(templates.iterdir()):
        dest = dest_dir / render(template.name).removesuffix(".template")
        if dest.exists():
            die(f"{dest} already exists — pick another name.")
        rendered[dest] = render(template.read_text())


# --- the registries ---------------------------------------------------------
#
# Anchored on a pattern, not a line number, and loud if the anchor is gone — a
# silently skipped edit would leave a subapp reachable from nowhere. Each entry
# goes last in its list. Patches accumulate in memory (chained, so a file edited
# twice sees the first edit); they are written in the commit phase below.

patches = {}  # path -> patched contents


def plan_edit(path, pattern, addition, before=False, group=None):
    """Insert `addition` after the last match of `pattern`, before the first
    (`before`), or at the end of capture `group` of the first (a value inside
    a line, such as a worker's list)."""
    text = patches.get(path)
    if text is None:
        text = path.read_text()
    found = list(re.finditer(pattern, text, re.M))
    if not found:
        die(f"Could not find {pattern!r} in {path} — add the entry by hand.")
    if group is not None:
        at = found[0].end(group)
    else:
        at = found[0].start() if before else found[-1].end()
    patches[path] = text[:at] + addition + text[at:]


server_py = PY_SRC / "server.py"
plan_edit(server_py, r"^import [a-z_][a-z0-9_]*\n", f"import {pkg}\n")
# The description is /docs' group heading for this app; the label is a best guess,
# worth replacing with a real sentence. Written as a Python string literal so a
# quote in the label cannot break server.py.
plan_edit(
    server_py,
    r"^\]\n",
    f'    AppEntry(\n'
    f'        "{slug}",\n'
    f'        {pkg},\n'
    f'        {py_str(label + ".")},\n'
    f'    ),\n',
    before=True,
)

# Two separate blocks in that file, each anchored on its own pattern — the
# entry goes after the last line of its own block, not at the end of the other's.
servers_ts = WEB / "lib" / "servers.ts"
plan_edit(
    servers_ts,
    r"^export const \w+_WS_PATH = .*\n",
    f"export const {ws_path_const} = '/api/{slug}/ws'\n",
)
plan_edit(
    servers_ts,
    r"^export const \w+_API_PATH = .*\n",
    f"export const {api_path_const} = '/api/{slug}'\n",
)

app_tsx = WEB / "App.tsx"
plan_edit(
    app_tsx,
    r"^import .*@/pages/.*\n",
    f"import {{ {name}Page }} from '@/pages/{slug}/{name}Page'\n",
)
# Above the catch-all route: below it, the new route would never match.
plan_edit(
    app_tsx,
    r'^ *<Route path="\*".*\n',
    f'          <Route path="{slug}" element={{<{name}Page />}} />\n',
    before=True,
)

# Written as a single-quoted TS string literal: an apostrophe in the label (the
# classic "Operator's View") used to terminate this string and emit broken TS.
plan_edit(
    WEB / "components" / "AppLayout.tsx",
    r"^\]\n",
    f"  {{ to: '/{slug}', label: {ts_squote(label)}, end: false }},\n",
    before=True,
)


# The module set: under compose and k8s the module-worker hosts the modules
# (the server hosts none there), so its pipeline and module lists each gain the
# new one. Anchored on the worker's own name, so another worker's lists are
# never the ones patched.
if template_set == "module":
    for var, addition in (("PSWAMP_WORKER_PIPELINES", f",{pkg}.pipeline:PIPELINE"), ("PSWAMP_WORKER_MODULES", f",{slug}")):
        plan_edit(
            Path("docker-compose.yml"),
            rf'^  module-worker:\n(?:.*\n)*?\s*{var}: "?([^"\n]*)',
            addition,
            group=1,
        )
        plan_edit(
            Path("k8s/p-swamp-local.yaml"),
            rf'name: p-swamp-module-worker\n(?:.*\n)*?\s*- name: {var}\n\s*value: "?([^"\n]*)',
            addition,
            group=1,
        )


# --- commit: create dirs, write files, write patches, or roll back ----------
#
# The first write to the working tree happens here. If any write fails part way,
# restore every patched file and remove the new folders, so a failure never
# leaves a partial subapp for the contributor to untangle by hand.

created_dirs = []
originals = {path: path.read_text() for path in patches}
try:
    for dest_dir in (api_dir, page_dir):
        dest_dir.mkdir(parents=True)
        created_dirs.append(dest_dir)
    for dest, content in rendered.items():
        dest.write_text(content)
        print(f"  new      {dest}")
    for path, text in patches.items():
        path.write_text(text)
        print(f"  patched  {path}")
except Exception:
    for path, text in originals.items():
        path.write_text(text)
    for dest_dir in reversed(created_dirs):
        shutil.rmtree(dest_dir, ignore_errors=True)
    raise

if template_set == "module":
    print(f"\n\033[1m{label}: page /{slug}, socket /api/{slug}/ws, module {pkg}/{pkg}_module.py\033[0m")
else:
    print(f"\n\033[1m{label}: page /{slug}, socket /api/{slug}/ws, "
          f"commands POST /api/{slug}/count/…\033[0m")
print("  the api contract is regenerated next — commit doc/api/openapi.json and")
print("  app/client-web/src/api/schema.ts along with the new subapp.")
PY

# Regenerate the contract BEFORE the checks: the new page imports its wire type
# from the TypeScript generated off the new package's WS_MESSAGE, so until this
# runs the subapp does not type-check. Runs even under NO_CHECK=1 — skipping the
# checks saves time, a stale contract just leaves a broken tree.
scripts/generate-api-contract.sh

[ "${NO_CHECK:-0}" = 1 ] || scripts/error_check.sh

cat <<'EOF'

Restart ./scripts/start-local-hotloaded-pswamp-server.sh — a new Python package
needs the rebuild, not just compose watch — and the page is in the nav.
EOF
