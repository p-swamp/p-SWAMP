#!/usr/bin/env bash
# Deploy the project to a local minikube cluster — for testing k8s configs. For
# rapid local dev with live reload, use start-local-hotloaded-pswamp-server.sh
# (docker compose) instead.
#
# Checks the committed api contract matches the code, builds the image straight
# into minikube (no registry/push), applies k8s/, forces a rollout so the rebuilt
# :latest is picked up, waits for readiness, and prints the WebSocket URL.
#
# Needs minikube + kubectl, plus uv + npx for the contract check. Missing tools
# stop the script with a pointer; it installs nothing.
#
# Flags: NO_CHECK=1 skips the contract preflight (and its uv/npx requirement),
# NO_BROWSER=1 skips opening the client, NO_LOGS=1 returns to the prompt instead
# of tailing logs.
set -euo pipefail

# Run from the repo root regardless of where the script is invoked from.
cd "$(dirname "$0")/.."

# --- Preflight: required tooling -------------------------------------------
if ! command -v minikube >/dev/null 2>&1; then
  echo "minikube not found. Install it: https://minikube.sigs.k8s.io/docs/start/" >&2
  exit 1
fi
if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found. Install it: https://kubernetes.io/docs/tasks/tools/" >&2
  exit 1
fi

# --- Preflight: the api contract is not stale -------------------------------
#
# Read-only, BEFORE the cluster start and image build: this is the one failure
# this path can't otherwise catch, and failing here costs seconds not a full build.
#
# Why it can't be caught later: the build runs `tsc -b`, but a *stale* schema.ts
# agrees with the client perfectly — both are equally behind the Python, and tsc
# only compares TypeScript to TypeScript. So the image builds clean and the pod
# serves a client expecting fields the server no longer sends. Regenerating and
# diffing is the only thing that notices.
#
# Needs uv + npx (it imports the app for its description, then generates TS). The
# script exits loudly if either is missing. NO_CHECK=1 skips it — for knowingly
# deploying a WIP contract, not for getting past a red check.
if [ "${NO_CHECK:-0}" != 1 ]; then
  echo "Checking the api contract is up to date..."
  if ! scripts/generate-api-contract.sh --check; then
    echo >&2
    echo "Refusing to deploy: the committed api contract does not match the code." >&2
    echo "The image would build fine and serve a web client built from stale types." >&2
    echo >&2
    echo "  scripts/generate-api-contract.sh      # regenerate, then commit both files" >&2
    echo "  NO_CHECK=1 $0   # or deploy anyway" >&2
    exit 1
  fi
fi

# --- Ensure the cluster is running -----------------------------------------
if ! minikube status >/dev/null 2>&1; then
  echo "Starting minikube..."
  minikube start
fi

# --- Build the image into minikube -----------------------------------------
# Build inside minikube's runtime so the image lands where the kubelet looks (and
# the arch matches the node — matters on arm64).
echo "Building p-swamp:latest into minikube..."
# `minikube image build` exits 0 even when the build fails (minikube#12986), so
# check its log for BuildKit's failure line, and that the image is there.
BUILD_LOG="$(mktemp)"
minikube image build -t p-swamp:latest . 2>&1 | tee "$BUILD_LOG"
if grep -q '^ERROR: failed to' "$BUILD_LOG"; then
  rm -f "$BUILD_LOG"
  echo "Refusing to deploy: the image build failed (see the error above)." >&2
  exit 1
fi
rm -f "$BUILD_LOG"
if ! minikube image ls | grep -q '/p-swamp:latest$'; then
  echo "Refusing to deploy: p-swamp:latest is not in minikube's image store." >&2
  exit 1
fi

# --- Apply manifests and roll out ------------------------------------------
# The live feed's data file first, as the ConfigMap the server mounts. Built
# from the file so the example data stays a plain text file; idempotent.
echo "Applying manifests..."
kubectl create configmap p-swamp-pmu-data \
  --from-file=k8s/deployment_pmu_data_file_example.txt \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/p-swamp-local.yaml

# `kubectl apply` won't restart pods if the manifest text is unchanged, even
# though we just rebuilt :latest. Force new pods so the fresh image is used.
# Kafka first and never restarted: it is not built here, and a restart would
# empty its topics for nothing.
echo "Rolling out..."
BUILT="p-swamp-remote-data-stub p-swamp-module-worker p-swamp-batch-worker p-swamp"
kubectl rollout status deployment/p-swamp-kafka --timeout=300s
for name in $BUILT; do kubectl rollout restart "deployment/$name"; done
for name in $BUILT; do kubectl rollout status "deployment/$name" --timeout=120s; done

# --- Reach the Service ------------------------------------------------------
# The nodePort is fixed at 30080 and must stay in sync with k8s/p-swamp-local.yaml.
#
# `rollout status` above only waits for the pod; the Service's nodePort can take
# a moment longer to route, so poll /healthz before announcing a URL.
MINIKUBE_IP="$(minikube ip)"
NODE_PORT=30080
BASE_URL="http://${MINIKUBE_IP}:${NODE_PORT}"

# $1 = base url, $2 = attempts. A dot per attempt so the wait looks alive.
#
# `--connect-timeout 1` is what makes this fail fast, not `-m`: an unroutable node
# IP *drops* packets rather than refusing (no TCP reset), so without it every
# attempt burns its full `-m` timeout and sits silent for ~a minute before falling
# back — which reads as a hang. A refused or answered connection returns instantly.
wait_for_healthz() {
  local url="$1" attempts="$2" i
  for i in $(seq 1 "$attempts"); do
    if curl -sf --connect-timeout 1 -m 2 -o /dev/null "${url}/healthz"; then
      echo
      return 0
    fi
    printf '.'
    sleep 0.5
  done
  echo
  return 1
}

# Only a handful of attempts: `rollout status` already waited for the readiness
# probe (which *is* /healthz), so a routable NodePort answers on the first try.
# The budget exists only to detect the macOS no-route case fast.
printf '\nWaiting for %s/healthz ' "$BASE_URL"
if ! wait_for_healthz "$BASE_URL" 5; then
  # NodePort unreachable. On macOS/Windows the docker driver runs the node in a
  # Linux VM whose bridge the host has no route to, so `minikube ip` never answers
  # — the deployment is fine, the path isn't. (On Linux the bridge is routable and
  # we never get here.) Tunnel to the Service and use localhost instead, so
  # everything downstream (browser, WebSocket, healthz) works the same on both.
  echo "NodePort ${MINIKUBE_IP}:${NODE_PORT} is not routable from this host (expected on macOS/Windows"
  echo "with the docker driver) — forwarding a local port to the Service instead."
  kubectl port-forward "service/p-swamp" "${NODE_PORT}:8000" >/dev/null 2>&1 &
  PORT_FORWARD_PID=$!
  # Take the tunnel down with the script, however it exits.
  trap 'kill "$PORT_FORWARD_PID" 2>/dev/null || true' EXIT INT TERM
  BASE_URL="http://127.0.0.1:${NODE_PORT}"
  # More attempts, all cheap: loopback refuses a not-yet-bound tunnel instantly.
  # The budget is really for the tunnel to finish binding.
  printf 'Waiting for %s/healthz ' "$BASE_URL"
  if ! wait_for_healthz "$BASE_URL" 30; then
    echo "Port-forward did not come up either; the deployment may still be starting." >&2
    echo "Check with: kubectl get pods -l app=p-swamp" >&2
    exit 1
  fi
fi

WS_HOST="${BASE_URL#http://}"
echo
echo "p-swamp is up. Point the client's 'Local minikube' entry at:"
echo "    ws://${WS_HOST}/api/time-window/ws"
echo
echo "Web client:    ${BASE_URL}/"
echo "API docs:      ${BASE_URL}/docs  (ReDoc at /redoc, raw document at /openapi.json)"
echo "Health check:  curl -fsS ${BASE_URL}/healthz"

# --- Open the web client ----------------------------------------------------
# Hand the URL to the platform's launcher. NO_BROWSER=1 skips it (e.g. over SSH).
if [ -z "${NO_BROWSER:-}" ]; then
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${BASE_URL}/" >/dev/null 2>&1
  elif command -v open >/dev/null 2>&1; then
    open "${BASE_URL}/" >/dev/null 2>&1
  else
    echo "Could not find a browser launcher (xdg-open/open); open ${BASE_URL}/ manually."
  fi
fi

# --- Follow the server logs -------------------------------------------------
# Leave a live log stream in this terminal so you can watch client connects and
# playback commands as you drive the client. Ctrl-C stops only the tail — the
# deployment keeps running (re-attach with ./scripts/logs-minikube.sh). NO_LOGS=1
# returns to the prompt instead.
if [ -n "${NO_LOGS:-}" ]; then
  if [ -n "${PORT_FORWARD_PID:-}" ]; then
    echo
    echo "Note: the port-forward above dies with this script, so ${BASE_URL}/ goes away." >&2
    echo "Re-open it in its own terminal with:" >&2
    echo "    kubectl port-forward service/p-swamp ${NODE_PORT}:8000" >&2
  fi
  exit 0
fi

echo
if [ -n "${PORT_FORWARD_PID:-}" ]; then
  echo "Keeping the port-forward open for as long as this runs — Ctrl-C closes both"
  echo "the tail and the tunnel (the deployment keeps running either way)."
fi
echo "Following server logs (Ctrl-C stops the tail, not the deployment)..."
echo
# Not `exec`: it would replace this shell and orphan the port-forward instead of
# letting the EXIT trap clean it up.
#
# Backgrounded + `wait`, not foreground, because bash defers a trap until the
# foreground command returns — and `kubectl logs -f` never returns. `wait` is
# interruptible, so the trap fires immediately whether via Ctrl-C or `kill`.
# `set -m` gives the log tail its own process group: logs-minikube.sh is a
# pipeline (kubectl | grep), so killing just its shell would orphan the tail;
# a group of its own lets us signal the whole thing with `kill -- -PID`.
set -m
./scripts/logs-minikube.sh &
LOGS_PID=$!
set +m
cleanup() {
  kill -- "-${LOGS_PID}" 2>/dev/null || kill "$LOGS_PID" 2>/dev/null || true
  [ -n "${PORT_FORWARD_PID:-}" ] && kill "$PORT_FORWARD_PID" 2>/dev/null
  return 0
}
trap cleanup EXIT INT TERM
wait "$LOGS_PID"
