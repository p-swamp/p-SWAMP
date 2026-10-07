"""The subapp and module generators: derive a name's spellings, render templates, patch registries.

The port of the Python that scripts/generate-new-subapp.sh carried in a heredoc.
Two template sets live in ``templates/`` beside this file (``templates/README.md``
explains them):

* ``subapp``: a per-client counter, a page and its api;
* ``module``: a module project over the core pipeline (``modules/<slug>/``:
  its code, tests and README), its messages (in ``pswamp_models``), its
  pipeline (in the transitional ``legacy/pswamp-wiring/``), its web api, a page
  showing its latest result, and the api's test; the module joins the
  workspace (``modules/*``), becomes a dependency of the wiring and of the
  server, and is added to the module-worker in docker-compose.yml and
  k8s/p-swamp-local.yaml. The caller re-locks (``uv lock``) afterwards.

Everything is computed in memory first, every rendered file and every registry
patch, and only then written. So a bad name, a taken name or a missing anchor
aborts with nothing written, and a failed write rolls back what was written.

Line endings: on a Windows checkout with ``core.autocrlf`` the registries are
CRLF. They are matched with LF (the patterns say ``\\n``) and written back with
the ending they had, so a generated subapp changes only the lines it adds.
"""

from __future__ import annotations

import json
import keyword
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATE_SETS = ("subapp", "module")
SUFFIX = ".template"

WEB = Path("app/client-web/src")
PY_SRC = Path("app/server-python/src")
MODULES = Path("modules")
MODELS = Path("models/src/pswamp_models")
SERVER_TESTS = Path("app/server-python/tests")
# Transitional (until pipelines become TOML): the pipelines live in the wiring
# project, a portion of the pswamp_modules namespace like every module.
WIRING = Path("legacy/pswamp-wiring")
PIPELINES = WIRING / "src" / "pswamp_modules" / "pipelines"
SERVER_MANIFEST = Path("app/server-python/pyproject.toml")
WIRING_MANIFEST = WIRING / "pyproject.toml"
# Test folders that run in one pytest session with the server's and are not
# packages, so a test file name must be unique across all of them. The module
# projects' and the wiring's are globbed.
NON_PACKAGE_TESTS = (SERVER_TESTS, Path("models/tests"), Path("core/tests"), Path("tools/tests"))
NON_PACKAGE_TEST_GLOBS = ("modules/*/tests", "legacy/*/tests")
# The workspace's own distribution names: a module's, pswamp-<slug>, must not be one.
TAKEN_DISTRIBUTIONS = {"pswamp-models", "pswamp-core", "pswamp-tools", "pswamp-server", "pswamp-wiring"}

# The worker lists a module joins, as patterns whose group 1 is the list's value.
# check-generators reads the patched lists back with the same patterns.
COMPOSE = Path("docker-compose.yml")
K8S = Path("k8s/p-swamp-local.yaml")
WORKER_LIST_PATTERNS = {
    COMPOSE: r'^  module-worker:\n(?:.*\n)*?\s*{var}: "?([^"\n]*)',
    K8S: r'name: p-swamp-module-worker\n(?:.*\n)*?\s*- name: {var}\n\s*value: "?([^"\n]*)',
}


class GenerateError(RuntimeError):
    """The name is unusable or taken, or a registry anchor is gone. Nothing was written."""


@dataclass(frozen=True)
class Names:
    """The name in every shape it takes. Templates spell them ``__SLUG__`` … ``__LABEL__``.

    ============== ====================== ===========================================
    slug           grid-overview          URL, page folder, /api prefix
    pkg            grid_overview          Python package (an identifier); in the
                                          module set also the module's package
    name           GridOverview           React component, hook, model class
    ws_path_const  GRID_OVERVIEW_WS_PATH  ws path const in lib/servers.ts
    api_path_const GRID_OVERVIEW_API_PATH REST prefix const, same file
    upper          GRID_OVERVIEW          environment variable prefix (module set)
    ============== ====================== ===========================================

    Two path consts because the two directions use two transports: state down
    the socket, commands up as POSTs (see AGENTS.md).
    """

    slug: str
    label: str
    pkg: str
    name: str
    ws_path_const: str
    api_path_const: str
    upper: str

    def tokens(self) -> tuple[tuple[str, str], ...]:
        return (
            ("__SLUG__", self.slug),
            ("__PKG__", self.pkg),
            ("__NAME__", self.name),
            ("__WS_PATH_CONST__", self.ws_path_const),
            ("__API_PATH_CONST__", self.api_path_const),
            ("__UPPER__", self.upper),
            ("__LABEL__", self.label),
        )

    def render(self, text: str) -> str:
        for token, value in self.tokens():
            text = text.replace(token, value)
        return text


def derive_names(slug: str, label: str) -> Names:
    """Validate ``slug`` and ``label`` and derive every spelling, or :class:`GenerateError`."""
    pkg = slug.replace("-", "_")
    # The 32-char cap keeps the rendered Python lines short and readable.
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", slug) or len(slug) > 32 or keyword.iskeyword(pkg):
        raise GenerateError(f"{slug!r} is not usable: give lowercase words joined by hyphens, max 32 chars.")
    # The label is free text and lands in six places: a single-quoted TS string
    # (the nav entry), a double-quoted Python string (the AppEntry description),
    # two Python docstrings, a JSX text node and two JS comments. The two code
    # strings are escaped when written (py_str / ts_squote). The four prose sites
    # cannot be escaped by a token substitution, so reject what would break them:
    # angle brackets and braces (JSX), a backtick or backslash, and the comment
    # (`*/`) / docstring terminators. Everyday punctuation stays allowed:
    # "Operator's View" is a perfectly good label.
    if (
        not label.strip()
        or len(label) > 48
        or set(label) & set("<>{}\\`")
        or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in label)
        or "*/" in label
        or '"""' in label
    ):
        raise GenerateError(
            f"{label!r} is not usable as a nav label: give a short human phrase "
            "(max 48 chars) without angle brackets, braces, backslashes, backticks "
            "or control characters."
        )
    upper = pkg.upper()
    return Names(
        slug=slug,
        label=label,
        pkg=pkg,
        name="".join(word.capitalize() for word in slug.split("-")),
        ws_path_const=f"{upper}_WS_PATH",
        api_path_const=f"{upper}_API_PATH",
        upper=upper,
    )


def py_str(value: str) -> str:
    """``value`` as a Python string literal (JSON strings are a subset of Python's)."""
    return json.dumps(value)


def ts_squote(value: str) -> str:
    """``value`` as a single-quoted TS string literal, the style of servers.ts and AppLayout.tsx."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def read_text(path: Path) -> tuple[str, str]:
    """``(text with LF endings, the file's own newline)``."""
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), newline


def write_text(path: Path, text: str, newline: str = "\n") -> None:
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


@dataclass
class Plan:
    """The whole change set, in memory. Paths are relative to ``root``."""

    root: Path
    names: Names
    template_set: str
    new_dirs: list[Path] = field(default_factory=list)
    rendered: dict[Path, str] = field(default_factory=dict)
    patches: dict[Path, str] = field(default_factory=dict)
    newlines: dict[Path, str] = field(default_factory=dict)

    def edit(self, path: Path, pattern: str, addition: str, *, before: bool = False, group: int | None = None) -> None:
        """Insert ``addition`` after the last match of ``pattern``, before the first (``before``),
        or at the end of capture ``group`` of the first (a value inside a line, such as a worker's list).

        Anchored on a pattern, not a line number, and loud if the anchor is gone: a
        silently skipped edit would leave a subapp reachable from nowhere. Edits
        chain, so a file edited twice sees the first edit.
        """
        text = self.patches.get(path)
        if text is None:
            text, self.newlines[path] = read_text(self.root / path)
        found = list(re.finditer(pattern, text, re.M))
        if not found:
            raise GenerateError(f"Could not find {pattern!r} in {path.as_posix()} — add the entry by hand.")
        if group is not None:
            at = found[0].end(group)
        else:
            at = found[0].start() if before else found[-1].end()
        self.patches[path] = text[:at] + addition + text[at:]


def plan(root: Path, slug: str, label: str, template_set: str = "subapp", templates: Path = TEMPLATES_DIR) -> Plan:
    """Compute every file and registry edit for a new app under ``root``; writes nothing."""
    if template_set not in TEMPLATE_SETS:
        raise GenerateError(f"template set {template_set!r}: use 'subapp' or 'module'.")
    names = derive_names(slug, label)
    result = Plan(root=root, names=names, template_set=template_set)

    page_dir = WEB / "pages" / names.slug
    api_dir = PY_SRC / names.pkg
    project_dir = module_project(names)
    package_dir = module_package(names)
    models_dir = MODELS / names.pkg
    if (root / page_dir).exists() or (root / api_dir).exists():
        raise GenerateError(f"{names.slug} already exists as a page or an api package — pick another name.")
    if template_set == "module":
        if (root / project_dir).exists():
            raise GenerateError(f"{project_dir.as_posix()} already exists — pick another name.")
        # Also what refuses `pipelines` and `sources`, the wiring's two packages.
        if names.pkg in namespace_packages(root):
            raise GenerateError(f"pswamp_modules.{names.pkg} already exists — pick another name.")
        if f"pswamp-{names.slug}" in TAKEN_DISTRIBUTIONS:
            raise GenerateError(f"pswamp-{names.slug} already exists as a workspace project — pick another name.")
        # And what refuses the producers already in the models (`common`, `pmu`, …).
        if (root / models_dir).exists():
            raise GenerateError(f"{models_dir.as_posix()} already exists — pick another name.")

    tset = templates / template_set
    sources = [(tset / "server-python", api_dir), (tset / "client-web", page_dir)]
    result.new_dirs = [api_dir, page_dir]
    # The module set: the module is a project of its own, modules/<slug>/ (its
    # manifest and README, its code in the pswamp_modules namespace, its tests),
    # which depends on the core and the models only; what it publishes goes to
    # the models, where every consumer imports it from; its pipeline goes to the
    # transitional wiring; the web api's test goes into the server's tests/.
    if template_set == "module":
        sources += [
            (tset / "models", models_dir),
            (tset / "module-project", project_dir),
            (tset / "module", package_dir),
            (tset / "module-tests", project_dir / "tests"),
            (tset / "pipeline", PIPELINES),
            (tset / "tests", SERVER_TESTS),
        ]
        result.new_dirs += [models_dir, project_dir, package_dir, project_dir / "tests"]

    # Every template is <filename>.template. A missing suffix is an error, not a
    # no-op, so the convention can't rot into "some of them".
    for folder, _ in sources:
        if not folder.is_dir():
            raise GenerateError(f"Missing {folder}/ — the templates live in {templates}.")
        for template in sorted(folder.iterdir()):
            if not template.name.endswith(SUFFIX):
                raise GenerateError(f"{template} must be named <filename>{SUFFIX} — see templates/README.md.")

    folders = test_folders(root)
    for folder, dest_dir in sources:
        for template in sorted(folder.iterdir()):
            dest = dest_dir / names.render(template.name).removesuffix(SUFFIX)
            if (root / dest).exists():
                raise GenerateError(f"{dest.as_posix()} already exists — pick another name.")
            # Every test folder runs in one pytest session and none is a
            # package, so a test file's name must be unique across all of them.
            if dest.name.startswith("test_") and dest.suffix == ".py":
                for other in folders:
                    if (root / other / dest.name).exists():
                        raise GenerateError(f"{(other / dest.name).as_posix()} already exists — pick another name.")
            text, _ = read_text(template)
            result.rendered[dest] = names.render(text)

    _plan_registries(result)
    return result


def module_project(names: Names) -> Path:
    return MODULES / names.slug


def module_package(names: Names) -> Path:
    return module_project(names) / "src" / "pswamp_modules" / names.pkg


def test_folders(root: Path) -> list[Path]:
    """Every non-package test folder in the one pytest session, relative to ``root``."""
    found = [folder for folder in NON_PACKAGE_TESTS if (root / folder).is_dir()]
    for pattern in NON_PACKAGE_TEST_GLOBS:
        found += sorted(path.relative_to(root) for path in root.glob(pattern) if path.is_dir())
    return found


def namespace_packages(root: Path) -> set[str]:
    """The packages already in the pswamp_modules namespace, whichever project holds them."""
    return {
        path.name
        for pattern in ("modules/*/src/pswamp_modules/*", "legacy/*/src/pswamp_modules/*")
        for path in root.glob(pattern)
        if path.is_dir() and path.name != "__pycache__"
    }


def _plan_registries(p: Plan) -> None:
    n = p.names
    server_py = PY_SRC / "server.py"
    p.edit(server_py, r"^import [a-z_][a-z0-9_]*\n", f"import {n.pkg}\n")
    # The description is /docs' group heading for this app; the label is a best
    # guess, worth replacing with a real sentence.
    p.edit(
        server_py,
        r"^\]\n",
        f'    AppEntry(\n        "{n.slug}",\n        {n.pkg},\n        {py_str(n.label + ".")},\n    ),\n',
        before=True,
    )

    # Two blocks in that file, each anchored on its own pattern.
    servers_ts = WEB / "lib" / "servers.ts"
    p.edit(servers_ts, r"^export const \w+_WS_PATH = .*\n", f"export const {n.ws_path_const} = '/api/{n.slug}/ws'\n")
    p.edit(servers_ts, r"^export const \w+_API_PATH = .*\n", f"export const {n.api_path_const} = '/api/{n.slug}'\n")

    app_tsx = WEB / "App.tsx"
    p.edit(app_tsx, r"^import .*@/pages/.*\n", f"import {{ {n.name}Page }} from '@/pages/{n.slug}/{n.name}Page'\n")
    # Above the catch-all route: below it, the new route would never match.
    p.edit(
        app_tsx,
        r'^ *<Route path="\*".*\n',
        f'          <Route path="{n.slug}" element={{<{n.name}Page />}} />\n',
        before=True,
    )

    p.edit(
        WEB / "components" / "AppLayout.tsx",
        r"^\]\n",
        f"  {{ to: '/{n.slug}', label: {ts_squote(n.label)}, end: false }},\n",
        before=True,
    )

    # The module set: the new project is a dependency of the wiring (its
    # pipeline imports the module) and of the server, each with its workspace
    # source. Anchored on the comment that heads each one's list of modules.
    if p.template_set == "module":
        dist = f"pswamp-{n.slug}"
        for manifest, heading in (
            (WIRING_MANIFEST, r"^    # The modules the pipelines in src/pswamp_modules/pipelines/ import\."),
            (SERVER_MANIFEST, r"^    # The modules, one project each \(modules/<name>/\)\."),
        ):
            p.edit(manifest, heading + r'\n(?:    "pswamp-[a-z0-9-]+",\n)*', f'    "{dist}",\n')
            p.edit(manifest, r"^pswamp-[a-z0-9-]+ = \{ workspace = true \}\n", f"{dist} = {{ workspace = true }}\n")

    # Under compose and k8s the module-worker hosts the modules,
    # so its pipeline and module lists each gain the new one. Anchored on the
    # worker's own name, so another worker's lists are never the ones patched.
    if p.template_set == "module":
        for var, addition in (
            ("PSWAMP_WORKER_PIPELINES", f",pswamp_modules.pipelines.{n.pkg}:PIPELINE"),
            ("PSWAMP_WORKER_MODULES", f",{n.slug}"),
        ):
            for path, pattern in WORKER_LIST_PATTERNS.items():
                p.edit(path, pattern.format(var=var), addition, group=1)


def apply(p: Plan, echo: Callable[[str], None] = print) -> None:
    """Write the plan. On any failure restore every patched file and remove what was created."""
    root = p.root
    created: list[Path] = []
    written: list[Path] = []
    originals = {path: (root / path).read_bytes() for path in p.patches}
    try:
        for directory in p.new_dirs:
            (root / directory).mkdir(parents=True)
            created.append(root / directory)
        for dest, content in p.rendered.items():
            write_text(root / dest, content)
            written.append(root / dest)
            echo(f"  new      {dest.as_posix()}")
        for path, text in p.patches.items():
            write_text(root / path, text, p.newlines.get(path, "\n"))
            echo(f"  patched  {path.as_posix()}")
    except Exception:
        for path, data in originals.items():
            (root / path).write_bytes(data)
        for dest in written:
            dest.unlink(missing_ok=True)
        for directory in reversed(created):
            shutil.rmtree(directory, ignore_errors=True)
        raise


def summary(p: Plan) -> str:
    n = p.names
    if p.template_set == "module":
        return (
            f"{n.label}: page /{n.slug}, socket /api/{n.slug}/ws, module project {module_project(n).as_posix()}/ "
            f"({module_package(n).as_posix()}/module.py), messages {(MODELS / n.pkg).as_posix()}/"
        )
    return f"{n.label}: page /{n.slug}, socket /api/{n.slug}/ws, commands POST /api/{n.slug}/count/…"
