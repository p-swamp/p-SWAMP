"""k8s/base as an outside overlay uses it: renamed, relabelled, re-imaged (see k8s/README.md).

Renders with `kubectl kustomize`, the way such an overlay does, and checks the
"Overlays:" comments in k8s/base/p-swamp.yaml that a render can show.
"""

import re
import shutil
import subprocess

import pytest
from pswamp_tools._paths import repo_root

yaml = pytest.importorskip("yaml")

pytestmark = pytest.mark.skipif(
    shutil.which("kubectl") is None, reason="kubectl not installed"
)

IMAGE = "registry.example.com/p-swamp:main-0000000"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """The base as two copies of the stack in one namespace would deploy it: the copy named "a"."""
    # Kustomize takes only relative paths within one tree, so the overlay goes
    # in a copy of k8s/, where an outside overlay's own checkout would have it.
    k8s = tmp_path_factory.mktemp("tree") / "k8s"
    shutil.copytree(repo_root() / "k8s", k8s)
    renamed = k8s / "overlays" / "test-renamed"
    final = k8s / "overlays" / "test-final"
    renamed.mkdir()
    final.mkdir()
    (renamed / "kustomization.yaml").write_text(
        f"""
resources: [../../base]
namespace: demo
nameSuffix: -a
labels:
  - pairs: {{app.kubernetes.io/instance: p-swamp-a}}
    includeSelectors: true
images:
  - name: p-swamp
    newName: {IMAGE.rsplit(":", 1)[0]}
    newTag: {IMAGE.rsplit(":", 1)[1]}
""",
        encoding="utf-8",
    )
    (final / "kustomization.yaml").write_text(
        """
resources: [../test-renamed]
components: [../../components/hosts]
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["kubectl", "kustomize", str(final)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _of(docs, kind):
    return {doc["metadata"]["name"]: doc for doc in docs if doc["kind"] == kind}


def _pod_specs(docs):
    return {
        name: d["spec"]["template"]["spec"]
        for name, d in _of(docs, "Deployment").items()
    }


def test_every_object_is_renamed(rendered):
    for doc in rendered:
        assert doc["metadata"]["name"].startswith("p-swamp"), doc["metadata"]["name"]
        assert "-a" in doc["metadata"]["name"], doc["metadata"]["name"]
        assert doc["metadata"]["namespace"] == "demo"


def test_hosts_name_the_renamed_services(rendered):
    services = _of(rendered, "Service")
    hosts = _of(rendered, "ConfigMap")["p-swamp-hosts-a"]["data"]
    assert hosts, "p-swamp-hosts is empty"
    for var, host in hosts.items():
        assert host in services, f"{var}={host} is no Service in the render"


def test_no_service_name_written_out(rendered):
    """A Service's name in an env value would survive the rename and reach another copy's pods."""
    names = "|".join(
        re.escape(name.removesuffix("-a")) for name in _of(rendered, "Service")
    )
    address = re.compile(rf"(^|//|@)({names})(:|/|$)")
    for deployment, spec in _pod_specs(rendered).items():
        for container in spec["containers"]:
            for env in container.get("env", []):
                value = str(env.get("value", ""))
                assert not address.search(value), (
                    f"{deployment}/{container['name']} {env['name']}={value}: "
                    "compose it from $(VAR) in p-swamp-hosts"
                )


def test_every_pod_reads_its_hosts(rendered):
    for deployment, spec in _pod_specs(rendered).items():
        for container in spec["containers"]:
            used = {
                var
                for env in container.get("env", [])
                for var in ("PSWAMP_KAFKA_HOST", "PSWAMP_REMOTE_DATA_HOST")
                if f"$({var})" in str(env.get("value", ""))
            }
            if used:
                refs = {
                    ref["configMapRef"]["name"]
                    for ref in container.get("envFrom", [])
                    if "configMapRef" in ref
                }
                assert "p-swamp-hosts-a" in refs, (
                    f"{deployment}/{container['name']} uses {used} without envFrom"
                )


def test_overlay_sets_every_p_swamp_image(rendered):
    for deployment, spec in _pod_specs(rendered).items():
        for container in spec["containers"]:
            assert container["image"] == IMAGE or container["image"].startswith(
                "apache/kafka:"
            ), (
                f"{deployment}/{container['name']}: {container['image']} (name the image p-swamp)"
            )


def test_restricted_pod_security(rendered):
    for deployment, spec in _pod_specs(rendered).items():
        pod = spec.get("securityContext", {})
        assert pod.get("runAsNonRoot") is True, deployment
        assert pod.get("seccompProfile", {}).get("type") == "RuntimeDefault", deployment
        for container in spec["containers"]:
            sc = container.get("securityContext", {})
            where = f"{deployment}/{container['name']}"
            assert sc.get("allowPrivilegeEscalation") is False, where
            assert sc.get("privileged") is not True, where
            assert sc.get("capabilities", {}).get("drop") == ["ALL"], where


def test_selectors_carry_overlay_labels(rendered):
    for name, deployment in _of(rendered, "Deployment").items():
        selector = deployment["spec"]["selector"]["matchLabels"]
        assert selector.get("app.kubernetes.io/instance") == "p-swamp-a", name
        assert "app" in selector, name


def test_server_is_reachable_by_port_name(rendered):
    service = _of(rendered, "Service")["p-swamp-a"]
    assert service["spec"]["type"] == "ClusterIP"
    assert "http" in {port["name"] for port in service["spec"]["ports"]}
    server = next(
        d
        for d in _of(rendered, "Deployment").values()
        if d["spec"]["selector"]["matchLabels"] == service["spec"]["selector"]
    )
    assert server["spec"]["replicas"] == 1
    assert server["spec"]["strategy"]["type"] == "Recreate"
