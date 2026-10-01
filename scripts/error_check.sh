#!/usr/bin/env bash
# Static "is the code sound?" check for the whole repo — run before pushing. The
# single definition of soundness: the pre-push hook and CI both call THIS script
# rather than reimplementing the checks, so local and server can't drift apart.
#
# Read-only — never edits files.
#
# Never starts the app (nothing binds a port). The one exception is the api
# contract check, which imports the FastAPI app for its own description and so
# needs the full server env — a cold run may sync it. Three parts:
#
#   Web client (app/client-web)
#     - tsc -b ....... type-check (also catches unused locals, bad imports)
#     - eslint . ..... lint (flat eslint.config.js, react-hooks etc)
#
#   Python (app/server-python + core + modules)
#     - uv lock --check  pyproject.toml vs uv.lock in sync (read-only)
#     - py_compile ..... syntax/AST errors (app/, core/, modules/, + the older root src/ package)
#     - ruff check ..... lint (pyflakes F — real bugs, not style), app/ + core/ + modules/, from the locked dev group
#
#   The api contract (doc/api/openapi.json + app/client-web/src/api/schema.ts)
#     - generate-api-contract.sh --check — both are generated and committed, so a
#       changed endpoint fails here instead of surprising another team's browser.
#       Fix with: scripts/generate-api-contract.sh
#
# All checks run even if one fails; exits non-zero if any did.
set -uo pipefail

# Run from the repo root regardless of where the script is invoked from.
cd "$(dirname "$0")/.." || exit 1

# GUI git frontends (magit, IDEs) launch hooks with a minimal PATH missing
# ~/.local/bin (uv) and nvm's node dir, so a push fine from a terminal fails here
# with "uv/npx: not found". Re-add them.
prepend_path() { case ":$PATH:" in *":$1:"*) ;; *) [ -d "$1" ] && PATH="$1:$PATH";; esac; }
prepend_path "$HOME/.local/bin"                  # uv
if ! command -v npx >/dev/null 2>&1; then         # node via nvm: newest installed
  newest_node_bin="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
  [ -n "$newest_node_bin" ] && prepend_path "$newest_node_bin"
fi
export PATH

# Fail early with a clear message if a tool still isn't reachable.
missing=()
for tool in node npx uv python3; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if [ "${#missing[@]}" -ne 0 ]; then
  printf '\033[31merror_check: required tool(s) not found on PATH: %s\033[0m\n' "${missing[*]}"
  printf 'PATH=%s\n' "$PATH"
  exit 1
fi

# Collect the names of failed checks so we can report them all at the end.
FAILURES=()
section() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
run() {
  # run <label> <cmd...> — execute a check, remember it if it fails.
  local label="$1"; shift
  if "$@"; then
    printf '\033[32m  ✓ %s\033[0m\n' "$label"
  else
    printf '\033[31m  ✗ %s\033[0m\n' "$label"
    FAILURES+=("$label")
  fi
}

# --- Web client: TypeScript + ESLint ----------------------------------------
section "Web client (app/client-web)"
(
  cd app/client-web || exit 1
  # Fresh checkout has no node_modules — install from the lockfile first.
  if [ ! -d node_modules ]; then
    echo "Installing web client dependencies (first run)…"
    npm ci
  fi
)
run "tsc (web type-check)" bash -c 'cd app/client-web && npx --no-install tsc -b'
run "eslint (web lint)"    bash -c 'cd app/client-web && npx --no-install eslint .'

# --- Python: lockfile + AST/compile + ruff lint -----------------------------
section "Python (app/server-python, core, modules)"

# Dependency manifest vs lockfile (the Python counterpart of `npm ci`), so nobody
# adds a dependency, forgets to re-lock, and only finds out when the Docker
# build's `uv export --locked` fails. `--check` never writes; `--offline` keeps
# the pre-push hook off the network. Fix with: (cd app/server-python && uv lock)
if [ -f app/server-python/pyproject.toml ]; then
  run "uv lock --check (deps vs lockfile)" \
    uv lock --check --offline --project app/server-python
fi

# Every .py under app/, core/ and modules/, excluding caches. NUL-delimited to survive odd paths.
# A `while read -d ''` loop, NOT `mapfile -d ''`: mapfile is bash 4+, and macOS
# ships bash 3.2, where it fails with "command not found", leaves PY_FILES unset,
# and silently skips all three Python checks while still printing "All checks
# passed". Keep this POSIX-ish; don't reintroduce a bash-4 builtin.
PY_FILES=()
while IFS= read -r -d '' py_file; do
  PY_FILES+=("$py_file")
done < <(find app core modules -name '*.py' -not -path '*/__pycache__/*' -not -path '*/.venv/*' -print0)

if [ "${#PY_FILES[@]}" -eq 0 ]; then
  echo "  (no Python files found)"
else
  # AST/syntax: compile each module. Third-party deps aren't needed just to parse.
  run "py_compile (Python syntax/AST)" python3 -m py_compile "${PY_FILES[@]}"

  # The older desktop pswamp package at root src/ ships in the image (installed
  # editable), so it must at least parse. It gets a syntax-only gate for now: it
  # is not yet lint-clean, so it is deliberately excluded from `ruff check` below.
  # TODO Add full ruff lint check on the older pswamp code (root src/). It has
  # ~334 pyflakes findings to triage first — see AGENTS.md "Two Python projects".
  if [ -d src ]; then
    SRC_PY_FILES=()
    while IFS= read -r -d '' py_file; do
      SRC_PY_FILES+=("$py_file")
    done < <(find src -name '*.py' -not -path '*/__pycache__/*' -print0)
    if [ "${#SRC_PY_FILES[@]}" -ne 0 ]; then
      run "py_compile (older pswamp src/, syntax only)" \
        python3 -m py_compile "${SRC_PY_FILES[@]}"
    fi
  fi

  # ruff is pinned in the dev group and locked, so the hook and every dev run the
  # exact same linter (a floating `uvx ruff` could fail a push on untouched code).
  # `--project` points uv at that manifest without a cd; `--only-group dev` skips
  # fastapi/uvicorn. --select F (pyflakes) is set EXPLICITLY and deliberately
  # narrow: it catches real bugs (undefined names, unused imports) only. This gate
  # checks correctness, not style — we do NOT select pycodestyle E or run
  # `ruff format`, nor inherit ruff's other opinionated families (I, B, S…).
  RUFF=(uv run --project app/server-python --only-group dev ruff)
  run "ruff check (Python lint)"   "${RUFF[@]}" check --select F app core modules
fi

# --- The published api contract ---------------------------------------------
#
# doc/api/openapi.json + app/client-web/src/api/schema.ts are generated from the
# server and committed, so an endpoint or socket-message change shows up as a
# reviewable diff; this check stops one being forgotten. Last, because it's most
# often fixed by regenerating. ~0.6 s warm (the dataset and grid model are lazy),
# but it's the only check needing the full server env, so a COLD run syncs
# numpy/scipy/pandas first.

run "api contract (spec matches code)" scripts/generate-api-contract.sh --check

# --- Summary ----------------------------------------------------------------
section "Summary"
if [ "${#FAILURES[@]}" -eq 0 ]; then
  printf '\033[32mAll checks passed.\033[0m\n'
  exit 0
fi
printf '\033[31m%d check(s) failed:\033[0m\n' "${#FAILURES[@]}"
printf '  - %s\n' "${FAILURES[@]}"
printf '\nIf it was the api contract, regenerate and commit it:\n'
printf '  scripts/generate-api-contract.sh\n'
exit 1
