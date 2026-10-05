#!/usr/bin/env bash
# End-to-end smoke test — "does the whole rig still work?", as one command.
#
#   scripts/e2e-smoke-test.sh                                 build a server, test it, stop it
#   SMOKETEST_URL=http://host:port scripts/e2e-smoke-test.sh  test a server already running
#
# The first form ALWAYS starts from scratch (every p-swamp container removed,
# image rebuilt, container recreated) — a reused server is not the tree you are
# testing; see teardown_pswamp for the three ways that has bitten. The second form
# touches nothing: the caller owns that server (the path CI takes).
#
# This is the manual test automated: the click-through of the Reference example
# that proves routing, the socket, the client id, a POST command and per-client
# state all still hold. It's the Reference example, not a p-SWAMP page, because
# that app is the stable path through the whole stack (AGENTS.md) — so a failure
# here is a broken rig, not a changed feature.
#
# Complements error_check.sh: that one never starts the app, this only starts it.
# Run both. It exercises the WIRE only, and would not notice a dead button or a
# blank panel; a Playwright browser test is the intended next layer on top.
#
# Checks, in order:
#   1. /healthz answers                — the process is serving
#   2. / serves the built web client   — the client is baked into the image
#   3. a deep link serves the shell    — SPAStaticFiles' history fallback
#   4. a trailing slash redirects      — the shell only works at the bare route
#   5. a missing asset still 404s      — that fallback isn't swallowing everything
#   6. /openapi.json has the commands  — the api describes itself
#   7. the counter flow                — POST commands in, state down the socket
#
# Steps 1-6 are curl; step 7 is tools/smoketest_reference_subapp.py, since bash
# can't speak a WebSocket (websockets is already in the server's env via
# uvicorn[standard]). Every step runs even if one fails; exits non-zero if any did.
set -uo pipefail

# Run from the repo root regardless of where the script is invoked from.
cd "$(dirname "$0")/.." || exit 1

# Same PATH repair as error_check.sh (minimal PATH under GUI git frontends / CI).
prepend_path() { case ":$PATH:" in *":$1:"*) ;; *) [ -d "$1" ] && PATH="$1:$PATH";; esac; }
prepend_path "$HOME/.local/bin"
export PATH

BASE_URL="${SMOKETEST_URL:-http://127.0.0.1:8000}"
# True once this script owns the stack — every run except the SMOKETEST_URL one,
# where the caller owns the server and this must not touch it.
STARTED_STACK=0

FAILURES=()
section() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
pass() { printf '    \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '    \033[31m✗\033[0m %s\n' "$1"; FAILURES+=("$1"); }

# check <label> <cmd...> — run a step, remember it if it fails.
check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$label"; else fail "$label"; fi
}

cleanup() {
  if [ "$STARTED_STACK" -eq 1 ]; then
    printf '\nStopping the server…\n'
    docker compose down --remove-orphans >/dev/null 2>&1
  fi
}

# Remove every p-SWAMP container on this daemon before starting. Never reuse a
# running one — it's not the tree you are testing, and it fails like a code bug:
#
#   * `restart: unless-stopped` means a container from days ago is likely still up
#     at whatever commit it was built from;
#   * compose `watch` syncs adds/edits but NOT deletes, so a long-lived container
#     accumulates modules the repo dropped — a deleted package keeps importing;
#   * `watch` only syncs source. The web client is baked in at build time, so
#     current Python can still serve a stale UI — exactly what checks 2-4 test.
#
# The cost of always rebuilding is one warm-cache image build.

teardown_pswamp() {
  local removed
  docker compose down --remove-orphans -t 5 >/dev/null 2>&1

  # Anything running a p-swamp image outside this compose project (a hand-started
  # `docker run`, or an older project name). Matched on image, not container name.
  # (No bash 4 here — see the AGENTS.md note on macOS's bash 3.2.)
  removed=""
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    docker rm -f "$id" >/dev/null 2>&1 && removed="$removed $id"
  done <<EOF
$(docker ps -aq --filter "ancestor=p-swamp:latest" 2>/dev/null)
EOF

  if [ -n "$removed" ]; then
    echo "    Removed stray p-swamp container(s):$removed"
  fi
}

# Poll until the server serves — unconditional, since with SMOKETEST_URL the
# caller may have launched it a moment ago (CI does), and the first check would
# otherwise race a still-booting server.
#
# --connect-timeout, not just -m: an address with no route drops packets rather
# than refusing, so an attempt otherwise burns its full timeout in silence. A dot
# per attempt, for the same reason.
wait_for_healthz() {
  local attempts=30
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS --connect-timeout 1 -m 3 "$BASE_URL/healthz" >/dev/null 2>&1; then
      [ "$i" -gt 1 ] && printf '\n'
      pass "GET /healthz answers"
      return 0
    fi
    printf '.'
    sleep 1
  done
  printf '\n'
  fail "GET /healthz answers (no response after ${attempts}s)"
  return 1
}

# --- Preflight ---------------------------------------------------------------
missing=()
needed=(curl uv)
[ -n "${SMOKETEST_URL:-}" ] || needed+=(docker)
for tool in "${needed[@]}"; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if [ "${#missing[@]}" -ne 0 ]; then
  printf '\033[31me2e-smoke-test: required tool(s) not found on PATH: %s\033[0m\n' "${missing[*]}"
  exit 1
fi

# --- Get a server to test ----------------------------------------------------
#
# The container, not `uv run src/server.py`: the image is what ships and the only
# thing serving the built web client, which half the checks below are about.
section "Server under test"
if [ -n "${SMOKETEST_URL:-}" ]; then
  # The one path that touches nothing: the caller owns the server (CI builds and
  # runs the image itself), so don't go looking for containers to remove.
  echo "    Using the server at $SMOKETEST_URL (not managing its lifecycle)"
else
  # Down first, always — see teardown_pswamp for what reuse costs.
  echo "    Clearing any running p-swamp containers…"
  teardown_pswamp

  echo "    Starting the compose server from scratch (builds the image)…"
  # --wait blocks until docker-compose.yml's healthcheck passes (no polling loop).
  # --build / --force-recreate because compose otherwise reuses a stale image or
  # container even when the other is new.
  if ! docker compose up -d --build --force-recreate --wait; then
    printf '\033[31me2e-smoke-test: the server did not come up\033[0m\n'
    docker compose logs --tail 50 server
    docker compose down --remove-orphans >/dev/null 2>&1
    exit 1
  fi
  STARTED_STACK=1
  trap cleanup EXIT INT TERM
  echo "    Server up at $BASE_URL"
fi

# --- 1-6: the HTTP surface ---------------------------------------------------
section "HTTP surface"

wait_for_healthz

# Small predicates rather than `bash -c "…"` strings — nested-shell quoting is
# where this kind of script rots.
body_matches() { curl -fsS -m 5 "$BASE_URL$1" | grep -q "$2"; }
status_is() {
  [ "$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 -m 5 "$BASE_URL$1")" = "$2" ]
}
# Where a browser ends up after following redirects from $1.
lands_on() {
  [ "$(curl -s -o /dev/null -L -w '%{url_effective}' --connect-timeout 2 -m 5 "$BASE_URL$1")" = "$BASE_URL$2" ]
}

# `id="root"` is the mount point in index.html; an /assets/ reference proves this
# is the BUILT client, not the dev shell (which points at /src/main.tsx).
serves_built_client() {
  local body
  body="$(curl -fsS -m 5 "$BASE_URL$1")" || return 1
  grep -q 'id="root"' <<<"$body" && grep -q '/assets/' <<<"$body"
}
check "GET / serves the built web client" serves_built_client "/"

# A hard refresh on a page route must work — SPAStaticFiles returns index.html for
# a 404 outside assets/ and api/.
check "GET /reference-subapp serves the shell (deep link)" \
  body_matches "/reference-subapp" 'id="root"'

# The shell's asset urls are relative, so served at /reference-subapp/ it would
# look for them under /reference-subapp/assets/ and render blank. The server
# redirects to the bare route instead.
check "GET /reference-subapp/ redirects to /reference-subapp" \
  lands_on "/reference-subapp/" "/reference-subapp"

# …but that fallback must not answer for everything, or a wrong asset/endpoint URL
# would return HTML instead of failing loudly.
check "GET /assets/does-not-exist.js still 404s" \
  status_is "/assets/does-not-exist.js" 404

# Proof the document is served (not a staleness check — error_check.sh owns that).
check "GET /openapi.json describes the Reference example's commands" \
  body_matches "/openapi.json" 'reference_subapp_bump'

# --- 7: the counter flow, over the socket ------------------------------------
section "Reference example (commands up, state down)"
uv run --project app/server-python \
  python app/server-python/tools/smoketest_reference_subapp.py "$BASE_URL" \
  || FAILURES+=("counter flow")

# --- Report ------------------------------------------------------------------
if [ "${#FAILURES[@]}" -ne 0 ]; then
  printf '\n\033[31mSmoke test FAILED (%d):\033[0m\n' "${#FAILURES[@]}"
  for f in "${FAILURES[@]}"; do printf '  - %s\n' "$f"; done
  if [ "$STARTED_STACK" -eq 1 ]; then
    printf '\nLast 50 lines of server log:\n'
    docker compose logs --tail 50 server
  fi
  exit 1
fi

printf '\n\033[32mSmoke test passed — the rig works end to end.\033[0m\n'
