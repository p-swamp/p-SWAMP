"""Where each page of the documentation site comes from.

Most pages are files under ``doc/``, the site's ``docs_dir``. The rest are
collected from elsewhere in the repository by ``gen_pages.py`` (mkdocs-gen-files)
so that each lives beside the code it describes:

* ``modules/<name>/README.md``    -> ``modules/<name>/index.md``
* ``modules/<name>/docs/<rel>``   -> ``modules/<name>/<rel>``   (pages and images)
* ``modules/<name>/`` (generated) -> ``modules/<name>/api.md``  (its API reference)
* the READMEs in ``COLLECTED_READMES``

``hooks.py`` reads the same table, to resolve a link in a collected page against
the folder of the file it was written in, not against the page's place on the
site. One table for both, so the two cannot disagree.

Not part of the ``pswamp`` CLI: MkDocs loads this folder by path (``mkdocs.yml``
names ``hooks.py`` and ``gen_pages.py``), and it is kept outside ``doc/`` because
anything in ``docs_dir`` that is not Markdown would be published as a file.
"""

from __future__ import annotations

import posixpath
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS_DIR = "doc"

# Where a page is published from, as repo paths, and the branch an "edit" or a
# GitHub link points at.
GITHUB = "https://github.com/p-swamp/p-SWAMP"
BRANCH = "main"

# READMEs published as site pages, repo path -> site uri.
COLLECTED_READMES: dict[str, str] = {
    "modules/README.md": "developers/module-projects.md",
    "tools/README.md": "developers/cli.md",
    "k8s/README.md": "developers/deploying.md",
}

# In a module's docs/, these names are taken by the pages generated for it.
RESERVED_MODULE_PAGES = ("index.md", "api.md")


def module_names() -> list[str]:
    """Every module project: a folder under ``modules/`` with a README."""
    root = REPO / "modules"
    return sorted(p.name for p in root.iterdir() if (p / "README.md").is_file())


def module_doc_files(name: str) -> list[str]:
    """Every file in ``modules/<name>/docs/``, relative to that folder, posix."""
    docs = REPO / "modules" / name / "docs"
    if not docs.is_dir():
        return []
    return sorted(p.relative_to(docs).as_posix() for p in docs.rglob("*") if p.is_file())


@cache
def collected() -> dict[str, str]:
    """Every page or file published from outside ``doc/``: site uri -> repo path.

    The generated API pages are not in it: they have no source file.
    """
    pages = {uri: repo for repo, uri in COLLECTED_READMES.items()}
    for name in module_names():
        pages[f"modules/{name}/index.md"] = f"modules/{name}/README.md"
        for rel in module_doc_files(name):
            if rel in RESERVED_MODULE_PAGES:
                continue
            pages[f"modules/{name}/{rel}"] = f"modules/{name}/docs/{rel}"
    return pages


@cache
def _published_from() -> dict[str, str]:
    return {repo: uri for uri, repo in collected().items()}


def source_of(uri: str) -> str | None:
    """The repo path a site uri was written in; ``None`` for a page generated from nothing."""
    if uri in collected():
        return collected()[uri]
    if (REPO / DOCS_DIR / uri).is_file():
        return f"{DOCS_DIR}/{uri}"
    return None


def uri_of(repo_path: str) -> str | None:
    """The site uri a repo file is published as, if it is one of the site's sources.

    A folder stands for its README (or its index.md), as on GitHub. Whether the
    page is actually on the site (not excluded) is for the caller to check.
    """
    repo_path = repo_path.rstrip("/")
    folder = REPO / repo_path
    if folder.is_dir():
        for index in ("index.md", "README.md"):
            if (folder / index).is_file():
                return uri_of(f"{repo_path}/{index}")
        return None
    if repo_path in _published_from():
        return _published_from()[repo_path]
    prefix = DOCS_DIR + "/"
    if repo_path.startswith(prefix):
        return repo_path[len(prefix):]
    return None


def github_url(repo_path: str) -> str:
    """The repo path on GitHub: ``tree`` for a folder, ``blob`` for a file."""
    kind = "tree" if (REPO / repo_path).is_dir() else "blob"
    return f"{GITHUB}/{kind}/{BRANCH}/{repo_path}".rstrip("/")


def edit_path(repo_path: str) -> str:
    """The path "Edit this page" appends to ``edit_uri``, which ends in ``doc/``."""
    return posixpath.relpath(repo_path, DOCS_DIR)
