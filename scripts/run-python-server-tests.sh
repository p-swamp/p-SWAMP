#!/usr/bin/env bash
# Run the Python state server's unit test suite (app/server-python/tests/), and
# with it the core's (core/tests/) and the modules' (each module's tests/
# folder, under modules/).
#
# The stable interface for those tests: it hides the `uv run --project … pytest`
# incantation and the working-directory rule pytest needs to find its config.
#
# Every file under those is picked up automatically — pytest discovers
# test_*.py and `testpaths` in app/server-python/pyproject.toml names them — so
# a suite added there needs no change here. File names must be unique across
# app/server-python/tests/ and core/tests/, which are not packages.
#
# These are fast and hermetic: HubRegistry is driven with a stubbed Hub, so
# nothing binds a port and no server starts. They are deliberately NOT part of
# scripts/error_check.sh, which is strictly static (lockfile / AST / lint / api
# contract) and runs no test suites.
#
# The desktop "core" package's tests (desktop/tests/) are a separate suite in a
# separate env — see scripts/run-core-python-tests.sh.
#
# Any arguments are forwarded verbatim to pytest:
#   ./scripts/run-python-server-tests.sh                 # the whole suite
#   ./scripts/run-python-server-tests.sh -v              # verbose
#   ./scripts/run-python-server-tests.sh -k lock         # tests whose name matches "lock"
#   ./scripts/run-python-server-tests.sh tests/test_hub_registry.py::test_new_client_refused_when_all_slots_in_use
#
# Must run on bash 3.2 (macOS's /bin/bash), so no bash-4 builtins here.
set -uo pipefail

# Run from the repo root regardless of where this was invoked from.
cd "$(dirname "$0")/.." || exit 1

# uv lives in ~/.local/bin, which a minimal PATH (a GUI git frontend, a hook) can
# miss — the same fixup scripts/error_check.sh makes so a run that is fine from a
# terminal doesn't fail here with "uv: not found".
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) [ -d "$HOME/.local/bin" ] && PATH="$HOME/.local/bin:$PATH" ;;
esac
export PATH

if ! command -v uv >/dev/null 2>&1; then
  printf '\033[31mrun-python-server-tests: uv not found on PATH (needed for the server test env)\033[0m\n' >&2
  printf 'PATH=%s\n' "$PATH" >&2
  exit 1
fi

# pytest reads its config ([tool.pytest.ini_options]) and resolves pythonpath
# relative to app/server-python, so run from there. `uv run` uses the
# workspace's locked env (the root uv.lock) — pytest + pytest-asyncio from this
# member's dev group, plus the main deps the
# tests import (pswamp_web → pswamp). A cold run syncs that env first. exec so
# pytest's exit code is this script's.
#
# `-c pyproject.toml` pins that config. Without it pytest picks its config from
# the common ancestor of the paths it is given, so naming a file under tests/
# and one under ../../modules/ together would land on the workspace root's
# manifest and lose `pythonpath` and `asyncio_mode`.
cd app/server-python || exit 1
exec uv run pytest -c pyproject.toml "$@"
