"""Generate the site's pages that are not files under doc/ (run by mkdocs-gen-files).

* the READMEs in ``layout.COLLECTED_READMES`` (the CLI, the module projects,
  the k8s manifests), each published with "Edit this page" pointing at its source;
* the nav of ``doc/adr/`` (``adr/SUMMARY.md``, read by literate-nav), so the
  ADRs list in order and the template stays off the site.

Pages are written verbatim: their relative links are fixed at build time by
``hooks.py``, against ``layout.py``'s table of where each page comes from.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import mkdocs_gen_files

sys.path.insert(0, str(Path(__file__).parent))

import layout  # noqa: E402  (found through the line above)


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


for repo_path, uri in layout.COLLECTED_READMES.items():
    publish(uri, repo_path)
adr_nav()
