"""Generate the site's pages that are not files under doc/ (run by mkdocs-gen-files).

* the READMEs in ``layout.COLLECTED_READMES`` (the CLI, the module projects,
  the k8s manifests), each published with "Edit this page" pointing at its source;
* the nav of ``doc/adr/`` (``adr/SUMMARY.md``, read by literate-nav), so the
  ADRs list in order and the template stays off the site;
* one section per module (``modules/<name>/``): its README, the pages and files
  of its own ``docs/`` folder if it has one, and its API reference, generated
  from its docstrings and those of its messages. A new module is on the site
  with no edit here, once ``doc/modules/index.md`` says what it is for (a
  module that it does not link is a warning, so ``--strict`` fails on it).

Pages are written verbatim: their relative links are fixed at build time by
``hooks.py``, against ``layout.py``'s table of where each page comes from.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import tomllib
from pathlib import Path

import mkdocs_gen_files

sys.path.insert(0, str(Path(__file__).parent))

import layout  # noqa: E402  (found through the line above)

# A logger under "mkdocs.", so a warning counts for --strict.
log = logging.getLogger("mkdocs.plugins.pswamp_docs")


def read(repo_path: str) -> str:
    return (layout.REPO / repo_path).read_text(encoding="utf-8")


def publish(uri: str, repo_path: str) -> None:
    """Publish ``repo_path`` as the page ``uri``, editable at its source."""
    with mkdocs_gen_files.open(uri, "w", encoding="utf-8") as page:
        page.write(read(repo_path))
    mkdocs_gen_files.set_edit_path(uri, layout.edit_path(repo_path))


def title(repo_path: str) -> str:
    """A page's first heading, without an ``ADR-NNN:`` prefix."""
    match = re.search(r"^# (.+)$", read(repo_path), re.MULTILINE)
    text = match.group(1).strip() if match else Path(repo_path).stem
    return re.sub(r"^ADR-\d+:\s*", "", text)


def adr_nav() -> None:
    adrs = sorted(p.name for p in (layout.REPO / layout.DOCS_DIR / "adr").glob("[0-9][0-9][0-9]-*.md"))
    lines = ["* [Overview](README.md)"]
    lines += [f"* [{name[:3]} · {title(f'{layout.DOCS_DIR}/adr/{name}')}]({name})" for name in adrs]
    with mkdocs_gen_files.open("adr/SUMMARY.md", "w", encoding="utf-8") as nav:
        nav.write("\n".join(lines) + "\n")


def manifest(name: str) -> dict:
    return tomllib.loads(read(f"modules/{name}/pyproject.toml"))


def api_page(name: str) -> str:
    """The module's API reference: its package's docstrings, then its messages'."""
    project = manifest(name)
    package = project["tool"]["uv"]["build-backend"]["module-name"]  # pswamp_modules.<pkg>
    entry_points = project["project"].get("entry-points", {}).get("pswamp.modules", {})
    lines = [f"# {name}: API reference", ""]
    lines += [
        f"Generated from the docstrings of `{project['project']['name']}`. What the module reads, "
        "emits and accepts, and how to run it, is on its [overview](index.md).",
        "",
    ]
    for entry, target in entry_points.items():
        lines.append(f"Entry point `{entry}` (group `pswamp.modules`): `{target}`.")
        lines.append("")
    # A module's process() and its inputs/outputs rarely carry a docstring, and
    # they are the point of the page: show members whether documented or not.
    shown = ["    options:", "      show_if_no_docstring: true"]
    lines += [f"## `{package}`", "", f"::: {package}", *shown, ""]
    models = package.replace("pswamp_modules.", "pswamp_models.", 1)
    models_dir = layout.REPO / "models" / "src" / Path(*models.split("."))
    if models_dir.is_dir() or models_dir.with_suffix(".py").is_file():
        lines += [
            "## Its messages",
            "",
            "A module's messages live in `pswamp-models`, never in the module, so that anything "
            "can read them without importing the module.",
            "",
            f"::: {models}",
            *shown,
            "",
        ]
    return "\n".join(lines)


def module_nav_entries(name: str) -> list[str]:
    """The module's own pages, relative to its section, in nav order (excluding overview and API)."""
    pages = [rel for rel in layout.module_doc_files(name) if rel.endswith(".md")]
    for reserved in layout.RESERVED_MODULE_PAGES:
        if reserved in pages:
            log.warning(f"modules/{name}/docs/{reserved}: the name is taken by a generated page; rename it")
    summary = layout.REPO / "modules" / name / "docs" / "SUMMARY.md"
    if summary.is_file():
        return [line.rstrip() for line in summary.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [
        f"* [{title(f'modules/{name}/docs/{rel}')}]({rel})"
        for rel in pages
        if rel not in layout.RESERVED_MODULE_PAGES and rel != "SUMMARY.md"
    ]


def module_section(name: str) -> None:
    publish(f"modules/{name}/index.md", f"modules/{name}/README.md")
    for rel in layout.module_doc_files(name):
        if rel in layout.RESERVED_MODULE_PAGES or rel == "SUMMARY.md":
            continue
        source = layout.REPO / "modules" / name / "docs" / rel
        uri = f"modules/{name}/{rel}"
        if rel.endswith(".md"):
            publish(uri, f"modules/{name}/docs/{rel}")
        else:
            with mkdocs_gen_files.open(uri, "wb") as out:
                out.write(source.read_bytes())
    with mkdocs_gen_files.open(f"modules/{name}/api.md", "w", encoding="utf-8") as page:
        page.write(api_page(name))
    nav = ["* [Overview](index.md)", *module_nav_entries(name), "* [API reference](api.md)"]
    with mkdocs_gen_files.open(f"modules/{name}/SUMMARY.md", "w", encoding="utf-8") as out:
        out.write("\n".join(nav) + "\n")


def modules_nav(names: list[str]) -> None:
    """The Modules tab: the hand-written overview, then one section per module."""
    index = (layout.REPO / layout.DOCS_DIR / "modules" / "index.md").read_text(encoding="utf-8")
    for name in names:
        if f"({name}/index.md)" not in index and f"({name}/)" not in index:
            log.warning(
                f"module '{name}' is not described in doc/modules/index.md: add a line saying, in plain "
                f"words, what it is for, linking ({name}/index.md)"
            )
    lines = ["* [Overview](index.md)", *(f"* [{name}]({name}/)" for name in names)]
    with mkdocs_gen_files.open("modules/SUMMARY.md", "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")


def module_owning_models() -> dict[str, str]:
    """``pswamp_models.<pkg>`` packages a module publishes: package -> module folder.

    Those are rendered on the module's API page; rendering them twice would give
    each class two homes, and every cross-reference to it an ambiguous target.
    """
    owners = {}
    for name in layout.module_names():
        package = manifest(name)["tool"]["uv"]["build-backend"]["module-name"].split(".", 1)[1]
        if (layout.REPO / "models" / "src" / "pswamp_models" / package).is_dir():
            owners[package] = name
    return owners


def models_pages() -> None:
    """The Messages section: an overview of every producer package of pswamp_models,
    and one page for each that no module owns (a module's own are on its API page)."""
    root = layout.REPO / "models" / "src" / "pswamp_models"
    packages = sorted(p.name for p in root.iterdir() if (p / "__init__.py").is_file())
    owners = module_owning_models()
    rows, nav = [], ["* [Overview](index.md)"]
    for package in packages:
        module = f"pswamp_models.{package}"
        if package in owners:
            owner = owners[package]
            rows.append(f"| `{module}` | the [{owner}](../../../modules/{owner}/api.md) module's API page |")
            continue
        uri = f"reference/python/models/{package}.md"
        lines = [f"# `{module}`", "", f"::: {module}", "    options:", "      show_if_no_docstring: true", ""]
        with mkdocs_gen_files.open(uri, "w", encoding="utf-8") as page:
            page.write("\n".join(lines))
        mkdocs_gen_files.set_edit_path(uri, layout.edit_path(f"models/src/pswamp_models/{package}/__init__.py"))
        rows.append(f"| `{module}` | [its page]({package}.md) |")
        nav.append(f"* [{package}]({package}.md)")
    overview = [
        "# Messages",
        "",
        "Every message that crosses the transport or a socket is a versioned pydantic model in "
        "`pswamp-models`, in the package of whoever publishes it. The messages a module publishes are "
        "documented with that module; the others, shared by the core, the sources and the web backend, "
        "each have a page here.",
        "",
        "| Package | Documented on |",
        "|---|---|",
        *rows,
        "",
    ]
    with mkdocs_gen_files.open("reference/python/models/index.md", "w", encoding="utf-8") as page:
        page.write("\n".join(overview))
    with mkdocs_gen_files.open("reference/python/models/SUMMARY.md", "w", encoding="utf-8") as out:
        out.write("\n".join(nav) + "\n")


def web_api_page() -> None:
    """The web api: its socket channels as a table (OpenAPI has no notion of a socket),
    then its REST operations, rendered from the committed contract by neoteroi.

    No "Edit this page": the contract is generated (`pswamp api generate`).
    """
    contract = json.loads((layout.REPO / layout.DOCS_DIR / "api" / "openapi.json").read_text(encoding="utf-8"))
    rows = [
        f"| `{ch['path']}` | {ch['app']} | `{ch['message']['$ref'].rsplit('/', 1)[-1]}` |"
        for ch in sorted(contract.get("x-websocket-channels", []), key=lambda ch: ch["path"])
    ]
    lines = [
        "# Web API",
        "",
        f"The api between the web client and its server, version {contract['info']['version']}. It is "
        "generated from the server and committed as `doc/api/openapi.json`; "
        "[the client-server API](../the-client-server-api.md) explains it.",
        "",
        "**Two directions, two transports.** Everything a user triggers goes up as an HTTP `POST` under "
        "`/api/<app>/`, and is answered with a small `CommandAck`, never with state. Everything the server "
        "has to say comes down a WebSocket at `/api/<app>/ws`. Every request carries `?client_id=`.",
        "",
        "## WebSocket channels",
        "",
        "Each channel runs from the server to the client and carries one message, "
        "described with the other schemas at the end of this page.",
        "",
        "| Path | App | Message |",
        "|---|---|---|",
        *rows,
        "",
        "## Operations",
        "",
        "[OAD(./doc/api/openapi.json)]",
        "",
    ]
    with mkdocs_gen_files.open("reference/web-api.md", "w", encoding="utf-8") as page:
        page.write("\n".join(lines))


for repo_path, uri in layout.COLLECTED_READMES.items():
    publish(uri, repo_path)
adr_nav()
for module in layout.module_names():
    module_section(module)
modules_nav(layout.module_names())
models_pages()
web_api_page()
