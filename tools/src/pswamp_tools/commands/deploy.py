"""``pswamp deploy``: the real image in a local minikube cluster (were
start-pswamp-in-local-minikube-cluster.sh and logs-minikube.sh)."""

from __future__ import annotations

import contextlib
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import typer

from .. import _net, _ui, contract
from .._paths import repo_root
from .._proc import background, capture, require_tools, run, run_filtered

app = typer.Typer(
    help=(
        "Test the real artifact: build the image into a local minikube cluster and deploy "
        "k8s/p-swamp-local.yaml (`deploy minikube`), and follow its server logs (`deploy logs`). "
        "For day-to-day work with hot reload, use `uv run pswamp dev server` instead."
    ),
    no_args_is_help=True,
)

IMAGE = "p-swamp:latest"
MANIFEST = "k8s/p-swamp-local.yaml"
PMU_DATA = "k8s/deployment_pmu_data_file_example.txt"
# Must stay in sync with the Service's nodePort in k8s/p-swamp-local.yaml.
NODE_PORT = 30080
# Rebuilt here and so restarted; Kafka is not, and a restart would empty its topics.
BUILT = ("p-swamp-remote-data-stub", "p-swamp-module-worker", "p-swamp-batch-worker", "p-swamp")
HEALTHZ_LINE = "GET /healthz HTTP/1.1"
# A routable NodePort answers on the first try (rollout status already waited for
# the readiness probe, which IS /healthz); the budget only detects the no-route
# case quickly. The tunnel gets more: a not-yet-bound loopback port refuses at once.
NODEPORT_ATTEMPTS = 5
TUNNEL_ATTEMPTS = 30


class DeployFailed(RuntimeError):
    """A deploy step failed; the message says which and what to do."""


def _must(code: int, what: str) -> None:
    if code != 0:
        raise DeployFailed(f"{what} failed (exit {code})")


def build_failed(log: str) -> bool:
    """`minikube image build` exits 0 even when the build fails (minikube#12986): read its log."""
    return any(line.startswith("ERROR: failed to") for line in log.splitlines())


def image_present(listing: str, image: str = IMAGE) -> bool:
    return any(line.strip().endswith(f"/{image}") for line in listing.splitlines())


def _build_image(root: Path) -> None:
    _ui.section(f"Building {IMAGE} into minikube")
    # Inside minikube's runtime, so the image lands where the kubelet looks and
    # matches the node's arch. Output is streamed and kept, to read the failure line.
    process = subprocess.Popen(
        [require_tools("minikube")["minikube"], "image", "build", "-t", IMAGE, "."],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines: list[str] = []
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.decode("utf-8", errors="replace")
        lines.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()
    code = process.wait()
    if code != 0 or build_failed("".join(lines)):
        raise DeployFailed("Refusing to deploy: the image build failed (see the error above).")
    listing = capture(["minikube", "image", "ls"], cwd=root)
    if not image_present(listing.stdout):
        raise DeployFailed(f"Refusing to deploy: {IMAGE} is not in minikube's image store.")


def _apply(root: Path) -> None:
    _ui.section("Applying manifests")
    # The live feed's data file, as the ConfigMap the server mounts: rendered with
    # --dry-run and applied, so it is idempotent.
    rendered = capture(
        ["kubectl", "create", "configmap", "p-swamp-pmu-data", f"--from-file={PMU_DATA}",
         "--dry-run=client", "-o", "yaml"],
        cwd=root,
    )
    if rendered.returncode != 0:
        raise DeployFailed(f"kubectl create configmap failed: {rendered.stderr.strip()}")
    with tempfile.TemporaryDirectory() as tmp:
        configmap = Path(tmp) / "configmap.yaml"
        configmap.write_text(rendered.stdout, encoding="utf-8")
        _must(run(["kubectl", "apply", "-f", str(configmap)], cwd=root), "kubectl apply (configmap)")
    _must(run(["kubectl", "apply", "-f", MANIFEST], cwd=root), f"kubectl apply -f {MANIFEST}")

    _ui.section("Rolling out")
    # `kubectl apply` won't restart pods for an unchanged manifest, even though
    # :latest was just rebuilt, so force new pods.
    _must(run(["kubectl", "rollout", "status", "deployment/p-swamp-kafka", "--timeout=300s"], cwd=root),
          "rollout of p-swamp-kafka")
    for name in BUILT:
        _must(run(["kubectl", "rollout", "restart", f"deployment/{name}"], cwd=root), f"rollout restart {name}")
    for name in BUILT:
        _must(run(["kubectl", "rollout", "status", f"deployment/{name}", "--timeout=120s"], cwd=root),
              f"rollout of {name}")


@contextlib.contextmanager
def reachable_base_url(root: Path) -> Iterator[tuple[str, bool]]:
    """``(base url, tunnelled)`` of the Service, kept reachable for the ``with`` block.

    The NodePort first. On macOS/Windows with the docker driver the node is a
    container on a bridge inside the engine's VM, which the host has no route
    to: the deployment is fine, the path isn't. Then a ``kubectl port-forward``
    to the Service on the same port at 127.0.0.1, a child process stopped when
    the block exits, however it exits (Ctrl-C included).
    """
    ip = capture(["minikube", "ip"], cwd=root).stdout.strip()
    base = f"http://{ip}:{NODE_PORT}"
    _ui.console.print(f"\nWaiting for {base}/healthz ", end="")
    if ip and _net.wait_until_answers(f"{base}/healthz", NODEPORT_ATTEMPTS):
        yield base, False
        return
    _ui.info(
        f"NodePort {ip}:{NODE_PORT} is not routable from this host (expected on macOS/Windows with the "
        "docker driver); forwarding a local port to the Service instead."
    )
    with background(["kubectl", "port-forward", "service/p-swamp", f"{NODE_PORT}:8000"], cwd=root):
        base = f"http://127.0.0.1:{NODE_PORT}"
        _ui.console.print(f"Waiting for {base}/healthz ", end="")
        if not _net.wait_until_answers(f"{base}/healthz", TUNNEL_ATTEMPTS):
            raise DeployFailed(
                "the port-forward did not come up either; the deployment may still be starting.\n"
                "  Check with: kubectl get pods -l app=p-swamp"
            )
        yield base, True


def follow_logs(root: Path) -> int:
    """`kubectl logs -f` on the server, minus the /healthz probe lines."""
    return run_filtered(
        ["kubectl", "logs", "-f", "deployment/p-swamp", "--timestamps"], drop=HEALTHZ_LINE, cwd=root
    )


@app.command()
def minikube(
    no_check: bool = typer.Option(
        False, "--no-check", envvar="NO_CHECK",
        help="Skip the api contract preflight (for knowingly deploying a WIP contract, not for getting past a red check).",
    ),
    no_browser: bool = typer.Option(False, "--no-browser", envvar="NO_BROWSER", help="Don't open the web client."),
    no_logs: bool = typer.Option(
        False, "--no-logs", envvar="NO_LOGS", help="Return to the prompt instead of following the server logs."
    ),
) -> None:
    """Build the image into minikube, deploy k8s/p-swamp-local.yaml, open the client, follow the logs.

    1. Checks the committed api contract matches the code: the one staleness this
       path can't otherwise catch (a stale schema.ts type-checks against the client
       perfectly, so the image builds clean and serves a client expecting fields
       the server no longer sends). Failing here costs seconds, not a build.
    2. Starts minikube if it isn't running, builds the image straight into it (no
       registry), applies the manifests, and restarts the built deployments so the
       rebuilt :latest is used.
    3. Waits for /healthz on the NodePort (30080). Where the node isn't routable
       from the host (macOS/Windows with the docker driver) it starts
       `kubectl port-forward service/p-swamp 30080:8000` instead and uses
       http://127.0.0.1:30080; the tunnel lives as long as this command does.
    4. Opens the web client and follows the server logs (Ctrl-C stops the tail and
       the tunnel, never the deployment).

    Needs minikube and kubectl, plus uv and npx for the contract check. Installs nothing.
    """
    require_tools("minikube", "kubectl", purpose="by pswamp deploy minikube")
    root = repo_root()
    try:
        if not no_check:
            _ui.section("Checking the api contract is up to date")
            if contract.generate(check=True) != 0:
                raise DeployFailed(
                    "Refusing to deploy: the committed api contract does not match the code.\n"
                    "  The image would build fine and serve a web client built from stale types.\n"
                    "  -> uv run pswamp api generate   (regenerate, then commit both files)\n"
                    "  -> uv run pswamp deploy minikube --no-check   (or deploy anyway)"
                )

        if capture(["minikube", "status"], cwd=root).returncode != 0:
            _ui.section("Starting minikube")
            _must(run(["minikube", "start"], cwd=root), "minikube start")
        _build_image(root)
        _apply(root)

        with reachable_base_url(root) as (base, tunnelled):
            host = base.removeprefix("http://")
            _ui.console.print()
            _ui.console.print("p-swamp is up.", markup=False)
            _ui.console.print(f"Web client:    {base}/", markup=False)
            _ui.console.print(f"API docs:      {base}/docs  (ReDoc at /redoc, raw document at /openapi.json)", markup=False)
            _ui.console.print(f"Health check:  curl -fsS {base}/healthz", markup=False)
            _ui.console.print(f"A socket:      ws://{host}/api/time-window/ws", markup=False)
            if not no_browser:
                _net.open_browser(f"{base}/")

            if no_logs:
                if tunnelled:
                    _ui.console.print(
                        f"\nNote: the port-forward ends with this command, so {base}/ goes away.\n"
                        "Re-open it in its own terminal with:\n"
                        f"    kubectl port-forward service/p-swamp {NODE_PORT}:8000",
                        markup=False,
                    )
                return
            _ui.console.print()
            if tunnelled:
                _ui.console.print(
                    "Keeping the port-forward open for as long as this runs: Ctrl-C closes both the tail "
                    "and the tunnel (the deployment keeps running either way).",
                    markup=False,
                )
            _ui.console.print("Following server logs (Ctrl-C stops the tail, not the deployment)…\n", markup=False)
            follow_logs(root)
    except DeployFailed as exc:
        _ui.error(str(exc))
        raise typer.Exit(1) from None


@app.command()
def logs() -> None:
    """Follow the server's logs in the minikube deployment (the k8s `compose logs -f`).

    Streams client connects and playback commands as they happen, minus the
    /healthz probe lines. A follow is bound to one pod: re-running
    `pswamp deploy minikube` replaces the pod and ends the stream, so run this
    again once the new pod is ready. `kubectl logs deployment/p-swamp --previous`
    shows the last terminated pod's output.
    """
    require_tools("kubectl", purpose="by pswamp deploy logs")
    raise typer.Exit(follow_logs(repo_root()))
