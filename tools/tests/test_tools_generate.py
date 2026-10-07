"""The generators: name spellings, template rendering, registry anchors, and refusing a taken name.

Every test runs on a copy of the real registry files in a tmp dir, never on the tree.
"""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pswamp_tools import generate, main
from pswamp_tools._paths import repo_root

REGISTRIES = [
    Path("app/server-python/src/server.py"),
    Path("app/client-web/src/lib/servers.ts"),
    Path("app/client-web/src/App.tsx"),
    Path("app/client-web/src/components/AppLayout.tsx"),
    Path("docker-compose.yml"),
    Path("k8s/p-swamp-local.yaml"),
    Path("app/server-python/pyproject.toml"),
]


@pytest.fixture
def tree(tmp_path):
    """A tmp root holding copies of the registries and the folders the generators write into."""
    real = repo_root()
    for path in REGISTRIES:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(real / path, tmp_path / path)
    for folder in (
        "pipelines",
        "legacy/pswamp-wiring/src/pswamp_modules/sources",
        "modules/frame-stats/src/pswamp_modules/frame_stats",
        "modules/frame-stats/tests",
        "models/src/pswamp_models/pmu",
        "app/server-python/tests",
        "core/tests",
        "models/tests",
    ):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "app/client-web/src/pages").mkdir(parents=True, exist_ok=True)
    return tmp_path


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def text(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8")


# --- names ---------------------------------------------------------------


def test_every_spelling_is_derived_from_the_slug():
    names = generate.derive_names("grid-overview", "Grid Overview")
    assert names.pkg == "grid_overview"
    assert names.name == "GridOverview"
    assert names.ws_path_const == "GRID_OVERVIEW_WS_PATH"
    assert names.api_path_const == "GRID_OVERVIEW_API_PATH"
    assert names.upper == "GRID_OVERVIEW"


@pytest.mark.parametrize("slug", ["Grid", "grid_overview", "-grid", "grid-", "1grid", "a" * 33, "import", "a--b"])
def test_an_unusable_slug_is_refused(slug):
    with pytest.raises(generate.GenerateError, match="not usable"):
        generate.derive_names(slug, "Label")


@pytest.mark.parametrize("label", ["", "   ", "<b>", "{x}", "a\\b", "a`b", "x */ y", 'a"""b', "tab\there", "x" * 49])
def test_an_unusable_label_is_refused(label):
    with pytest.raises(generate.GenerateError, match="nav label"):
        generate.derive_names("grid", label)


def test_everyday_punctuation_in_a_label_is_escaped_not_refused():
    names = generate.derive_names("ops-view", "Operator's \"View\"")
    assert generate.ts_squote(names.label) == "'Operator\\'s \"View\"'"
    assert generate.py_str(names.label) == '"Operator\'s \\"View\\""'


def test_tokens_are_rendered_in_contents_and_file_names():
    names = generate.derive_names("grid-overview", "Grid Overview")
    assert names.render("use__NAME__Socket.ts") == "useGridOverviewSocket.ts"
    assert names.render("__WS_PATH_CONST__ __PKG__ __SLUG__ __LABEL__") == (
        "GRID_OVERVIEW_WS_PATH grid_overview grid-overview Grid Overview"
    )


def test_no_template_token_survives_rendering():
    names = generate.derive_names("zz-probe", "ZZ Probe")
    for template in generate.TEMPLATES_DIR.rglob("*.template"):
        rendered = names.render(template.read_text(encoding="utf-8"))
        assert "__SLUG__" not in rendered and "__NAME__" not in rendered and "__PKG__" not in rendered, template


# --- the subapp set ------------------------------------------------------------


def test_a_subapp_renders_its_folders_and_patches_every_registry(tree):
    plan = generate.plan(tree, "zz-probe", "ZZ Probe")
    generate.apply(plan, echo=lambda _: None)

    assert (tree / "app/server-python/src/zz_probe/__init__.py").is_file()
    assert (tree / "app/server-python/src/zz_probe/api.py").is_file()
    assert (tree / "app/client-web/src/pages/zz-probe/ZzProbePage.tsx").is_file()
    assert (tree / "app/client-web/src/pages/zz-probe/useZzProbeSocket.ts").is_file()

    server = text(tree, "app/server-python/src/server.py")
    assert "\nimport zz_probe\n" in server
    assert '        "zz-probe",\n        zz_probe,\n        "ZZ Probe.",\n' in server
    servers_ts = text(tree, "app/client-web/src/lib/servers.ts")
    assert "export const ZZ_PROBE_WS_PATH = '/api/zz-probe/ws'" in servers_ts
    assert "export const ZZ_PROBE_API_PATH = '/api/zz-probe'" in servers_ts
    app_tsx = text(tree, "app/client-web/src/App.tsx")
    assert "import { ZzProbePage } from '@/pages/zz-probe/ZzProbePage'" in app_tsx
    # Above the catch-all, or it would never match.
    assert app_tsx.index('<Route path="zz-probe"') < app_tsx.index('<Route path="*"')
    assert "{ to: '/zz-probe', label: 'ZZ Probe', end: false }," in text(
        tree, "app/client-web/src/components/AppLayout.tsx"
    )
    # The subapp set leaves the workers alone.
    assert "zz_probe" not in text(tree, "docker-compose.yml")


def test_each_path_const_goes_after_the_last_line_of_its_own_block(tree):
    generate.apply(generate.plan(tree, "zz-probe", "ZZ Probe"), echo=lambda _: None)
    lines = text(tree, "app/client-web/src/lib/servers.ts").splitlines()
    ws = [i for i, line in enumerate(lines) if "_WS_PATH = " in line]
    api = [i for i, line in enumerate(lines) if "_API_PATH = " in line]
    assert lines[ws[-1]].startswith("export const ZZ_PROBE_WS_PATH")
    assert lines[api[-1]].startswith("export const ZZ_PROBE_API_PATH")


def test_crlf_registries_keep_their_line_endings(tree):
    path = tree / "app/client-web/src/App.tsx"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    generate.apply(generate.plan(tree, "zz-probe", "ZZ Probe"), echo=lambda _: None)
    data = path.read_bytes()
    assert b"ZzProbePage" in data
    assert data.count(b"\n") == data.count(b"\r\n")


def test_a_taken_name_writes_nothing(tree):
    (tree / "app/client-web/src/pages/zz-probe").mkdir()
    before = snapshot(tree)
    with pytest.raises(generate.GenerateError, match="already exists"):
        generate.plan(tree, "zz-probe", "ZZ Probe")
    assert snapshot(tree) == before


def test_a_missing_anchor_writes_nothing(tree):
    path = tree / "app/client-web/src/components/AppLayout.tsx"
    path.write_text(path.read_text(encoding="utf-8").replace("\n]\n", "\n];\n"), encoding="utf-8")
    before = snapshot(tree)
    with pytest.raises(generate.GenerateError, match="Could not find"):
        generate.plan(tree, "zz-probe", "ZZ Probe")
    assert snapshot(tree) == before


def test_a_failed_write_rolls_everything_back(tree, monkeypatch):
    before = snapshot(tree)
    plan = generate.plan(tree, "zz-probe", "ZZ Probe")
    real_write = generate.write_text

    def failing(path, content, newline="\n"):
        if path.name == "App.tsx":
            raise OSError("disk full")
        real_write(path, content, newline)

    monkeypatch.setattr(generate, "write_text", failing)
    with pytest.raises(OSError):
        generate.apply(plan, echo=lambda _: None)
    assert snapshot(tree) == before
    assert not (tree / "app/server-python/src/zz_probe").exists()


# --- the module set ------------------------------------------------------------


def test_a_module_is_a_project_and_joins_the_module_worker(tree):
    generate.apply(generate.plan(tree, "zz-mod", "ZZ Mod", "module"), echo=lambda _: None)

    project = tree / "modules/zz-mod"
    assert (project / "pyproject.toml").is_file() and (project / "README.md").is_file()
    assert (project / "src/pswamp_modules/zz_mod/module.py").is_file()
    assert not (project / "src/pswamp_modules/__init__.py").exists()  # a namespace portion
    assert (project / "tests/test_zz_mod_module.py").is_file()
    assert not (project / "tests/__init__.py").exists()
    assert (project / "examples/run_zz_mod.py").is_file()
    assert (tree / "models/src/pswamp_models/zz_mod/results.py").is_file()
    assert (tree / "pipelines/zz-mod.toml").is_file()
    assert (tree / "app/server-python/tests/test_zz_mod.py").is_file()

    import re
    import tomllib

    manifest = tomllib.loads(text(tree, "modules/zz-mod/pyproject.toml"))
    assert manifest["project"]["name"] == "pswamp-zz-mod"
    assert manifest["project"]["entry-points"]["pswamp.modules"] == {"zz-mod": "pswamp_modules.zz_mod:ZzModModule"}
    assert manifest["tool"]["uv"]["build-backend"]["module-name"] == "pswamp_modules.zz_mod"
    pipeline = tomllib.loads(text(tree, "pipelines/zz-mod.toml"))
    assert (pipeline["app"], pipeline["modules"]) == ("zz-mod", ["zz-mod"])
    # A dependency (with its workspace source) of the server, and of nothing else.
    for path in ("app/server-python/pyproject.toml",):
        consumer = tomllib.loads(text(tree, path))
        assert "pswamp-zz-mod" in consumer["project"]["dependencies"], path
        assert consumer["tool"]["uv"]["sources"]["pswamp-zz-mod"] == {"workspace": True}, path
    # In the server's module list, not in its dev group.
    server = tomllib.loads(text(tree, "app/server-python/pyproject.toml"))
    assert "pswamp-zz-mod" not in server["dependency-groups"]["dev"]

    for path, pattern in generate.WORKER_LIST_PATTERNS.items():
        content = text(tree, path.as_posix())
        pipelines = re.search(pattern.format(var="PSWAMP_WORKER_PIPELINES"), content, re.M).group(1)
        modules = re.search(pattern.format(var="PSWAMP_WORKER_MODULES"), content, re.M).group(1)
        assert pipelines.endswith(",zz-mod.toml"), path
        assert modules.split(",")[-1] == "zz-mod", path
    # Only the module-worker: the batch worker's lists are untouched.
    assert text(tree, "docker-compose.yml").count("zz-mod.toml") == 1


def test_a_module_cannot_take_an_app_s_pipeline_file(tree):
    (tree / "pipelines/zz-mod.toml").write_text("", encoding="utf-8")
    with pytest.raises(generate.GenerateError, match="pipelines/zz-mod.toml already exists"):
        generate.plan(tree, "zz-mod", "ZZ Mod", "module")


@pytest.mark.parametrize("slug", ["sources", "frame-stats"])
def test_a_module_cannot_take_a_name_in_the_pswamp_modules_namespace(tree, slug):
    with pytest.raises(generate.GenerateError, match="already exists"):
        generate.plan(tree, slug, "Taken", "module")


@pytest.mark.parametrize("slug", ["core", "tools", "wiring"])
def test_a_module_cannot_take_the_distribution_name_of_a_workspace_project(tree, slug):
    with pytest.raises(generate.GenerateError, match=f"pswamp-{slug} already exists"):
        generate.plan(tree, slug, "Taken", "module")


def test_a_module_cannot_take_the_name_of_a_producer_in_the_models(tree):
    with pytest.raises(generate.GenerateError, match="models/src/pswamp_models/pmu already exists"):
        generate.plan(tree, "pmu", "PMU", "module")


@pytest.mark.parametrize("folder", ["core/tests", "models/tests", "modules/frame-stats/tests"])
@pytest.mark.parametrize("name", ["test_zz_mod.py", "test_zz_mod_module.py"])
def test_a_test_name_clashing_with_another_test_folder_is_refused(tree, folder, name):
    (tree / folder / name).write_text("", encoding="utf-8")
    with pytest.raises(generate.GenerateError, match=f"{folder}/{name}"):
        generate.plan(tree, "zz-mod", "ZZ Mod", "module")


# --- the CLI -------------------------------------------------------------------


@pytest.mark.parametrize("command", [["new"], ["new", "subapp"], ["new", "module"]], ids=" ".join)
def test_help_renders(command):
    result = CliRunner().invoke(main.app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_a_bad_name_is_one_error_line_and_exit_1(monkeypatch, tree):
    monkeypatch.setattr("pswamp_tools.commands.new.repo_root", lambda: tree)
    result = CliRunner().invoke(main.app, ["new", "subapp", "Bad_Name", "Label"])
    assert result.exit_code == 1
    assert "not usable" in result.output
