#!/usr/bin/env bash
# Prove both generators still produce working apps, without touching this
# working tree.
#
#   ./scripts/check-generators.sh
#
# In a throwaway git worktree holding a snapshot of this working tree
# (committed or not):
#   1. run generate-new-subapp.sh (a counter) and
#      generate-new-module-with-frontend.sh (a module and its page);
#   2. error_check.sh over the result;
#   3. the generated module's tests (the module's own tests/ folder, its
#      page's socket in the server's tests/), and the layering test over the
#      result;
#   4. import the module-worker's pipelines and modules as patched into
#      docker-compose.yml and k8s/p-swamp-local.yaml, from outside the server
#      tree, as a worker does.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd -P)"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) [ -d "$HOME/.local/bin" ] && PATH="$HOME/.local/bin:$PATH" ;; esac
export PATH

section() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

COUNTER=check-counter
MODULE=check-module
WORK="$(mktemp -d "${TMPDIR:-/tmp}/pswamp-generators.XXXXXX")"
TREE="$WORK/tree"

cleanup() {
  status=$?
  # The symlink first, so removing the worktree never reaches the real node_modules.
  if [ -L "$TREE/app/client-web/node_modules" ]; then rm "$TREE/app/client-web/node_modules"; fi
  git -C "$REPO" worktree remove --force "$TREE" >/dev/null 2>&1 || true
  git -C "$REPO" worktree prune
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT INT TERM

section "Snapshot this working tree into $TREE"
# A commit object of the tracked files as they are now; nothing is stashed.
rev="$(GIT_AUTHOR_NAME=check GIT_AUTHOR_EMAIL=check@localhost \
  GIT_COMMITTER_NAME=check GIT_COMMITTER_EMAIL=check@localhost git stash create)"
git worktree add --detach --quiet "$TREE" "${rev:-HEAD}"
git ls-files -z --others --exclude-standard > "$WORK/untracked"
if [ -s "$WORK/untracked" ]; then
  tar --null -T "$WORK/untracked" -cf - | tar -xf - -C "$TREE"
fi
if [ -d app/client-web/node_modules ]; then
  ln -s "$REPO/app/client-web/node_modules" "$TREE/app/client-web/node_modules"
fi
cd "$TREE"

section "Generate a counter subapp and a module app"
NO_CHECK=1 scripts/generate-new-subapp.sh "$COUNTER" "Check counter"
NO_CHECK=1 scripts/generate-new-module-with-frontend.sh "$MODULE" "Check module"

section "Static checks over the generated tree"
scripts/error_check.sh

section "The generated module's tests"
MODULE_PKG="$(printf '%s' "$MODULE" | tr - _)"
scripts/run-python-server-tests.sh -q "tests/test_${MODULE_PKG}.py" \
  "../../modules/pswamp_modules/${MODULE_PKG}/tests" \
  ../../modules/pswamp_modules/tests/test_layering.py

section "The module-worker hosts it, as patched"
(cd modules && MODULE="$MODULE" uv run --project ../app/server-python python - <<'PY'
import os
import re
from pathlib import Path

from pswamp_core.worker import load_pipelines

module = os.environ["MODULE"]
for path, prefix in (
    ("docker-compose.yml", r'^  module-worker:\n(?:.*\n)*?\s*{var}: "?([^"\n]*)'),
    ("k8s/p-swamp-local.yaml", r'name: p-swamp-module-worker\n(?:.*\n)*?\s*- name: {var}\n\s*value: "?([^"\n]*)'),
):
    text = (Path("..") / path).read_text()
    lists = {var: re.search(prefix.format(var=var), text, re.M).group(1)
             for var in ("PSWAMP_WORKER_PIPELINES", "PSWAMP_WORKER_MODULES")}
    names = set(lists["PSWAMP_WORKER_MODULES"].split(","))
    hosted = [m.name for p in load_pipelines(lists["PSWAMP_WORKER_PIPELINES"]) for m in p.modules if m.name in names]
    assert module in hosted, f"{path}: {hosted}"
    print(f"    {path}: {', '.join(hosted)}")
PY
)

printf '\n\033[32mBoth generators produce working apps.\033[0m\n'
