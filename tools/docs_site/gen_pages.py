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


for repo_path, uri in layout.COLLECTED_READMES.items():
    publish(uri, repo_path)
adr_nav()
for module in layout.module_names():
    module_section(module)
modules_nav(layout.module_names())
