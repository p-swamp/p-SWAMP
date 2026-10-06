#!/usr/bin/env bash
# Run the desktop "core" p-swamp package's test suite (desktop/tests/).
#
# Separate from the server tests (scripts/run-python-server-tests.sh) on purpose:
# a different Python project (desktop/pyproject.toml + desktop/uv.lock, the
# pswamp package, outside the uv workspace), resolved in a different env, and a very different kind of test.
#
# ── STARTING POINT — read before wiring this anywhere automated ──────────────
# Unlike the server suite, the core suite is NOT hermetic. Most files under
# tests/ need the desktop [full] extra (PySide6, kafka-python, nqkafka, tops-rt,
# paho-mqtt, …) AND external infrastructure at run time — a Kafka broker, an
# NQKafka / MQTT broker, a Qt display — and they carry no skip guards, so without
# that infra they ERROR rather than skip.

# The obvious next step for this stub is to mark the infra-bound tests (pytest
# markers or importorskip) so a bare run executes the hermetic subset and skips
# the rest, instead of failing. Until then, expect failures on a bare machine.
# ─────────────────────────────────────────────────────────────────────────────
#
# Runs in the desktop project's [full] env, which also carries pytest (via
# p-swamp[dev], pulled in by [full]). Arguments are forwarded to pytest, added
# after the tests/ target (paths are relative to desktop/):
#   ./scripts/run-core-python-tests.sh                         # all of tests/
#   ./scripts/run-core-python-tests.sh -k geo                  # a subset by name
#   ./scripts/run-core-python-tests.sh tests/monitoring -v     # one area, verbose
#
# Must run on bash 3.2 (macOS's /bin/bash), so no bash-4 builtins here.
set -uo pipefail

# Run from desktop/ regardless of where this was invoked from — the desktop
# project (and its tests/) live there, with their own lockfile, so `uv run`
# resolves against desktop/uv.lock and not the workspace's.
cd "$(dirname "$0")/../desktop" || exit 1

# uv lives in ~/.local/bin, which a minimal PATH (a GUI git frontend, a hook) can
# miss — the same fixup scripts/error_check.sh makes.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) [ -d "$HOME/.local/bin" ] && PATH="$HOME/.local/bin:$PATH" ;;
esac
export PATH

if ! command -v uv >/dev/null 2>&1; then
  printf '\033[31mrun-core-python-tests: uv not found on PATH (needed for the desktop test env)\033[0m\n' >&2
  printf 'PATH=%s\n' "$PATH" >&2
  exit 1
fi

printf '\033[1m==> Desktop core tests (desktop/tests/)\033[0m\n'
printf '    Needs the [full] extra + external infra (Kafka/NQKafka/MQTT brokers, a Qt display).\n'
printf '    A cold run builds the [full] env first (git deps: synchrophasor, nqkafka, tops-rt).\n\n'

# --extra full pulls the heavy deps the tests import (and pytest, via
# p-swamp[dev]). tests/ is passed explicitly because the desktop project sets
# no pytest testpaths — without it pytest would collect examples/ too. exec so
# pytest's exit code is this script's. We are already in desktop/ from the cd
# above.
exec uv run --extra full pytest tests/ "$@"
