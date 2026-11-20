"""MkDocs hooks: make every relative link in a page work on the site.

The pages are written to be read on GitHub first, so their links are relative to
the file they were written in: a module README links ``examples/plot.py`` and
``../../doc/module-cookbook.md``, a page in ``doc/`` links
``../.github/dependency-review-config.yml``. On the site, three things break
that: a collected page sits somewhere else than its source (``layout.py``), much
of what is linked is code, which is not on the site at all, and some pages are
kept off the site (``exclude_docs``).

So each relative link is resolved against the file the page was written in, and
then pointed at:

* the page or file on the site, when its target is published there;
* the target on GitHub otherwise (code, a workflow, an excluded page).

A target that does not exist is left alone, so MkDocs still reports it as the
broken link it is (and ``--strict`` fails on it). Links inside code are never
touched. The source files are not edited.
"""

from __future__ import annotations

import posixpath
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import layout  # noqa: E402  (found through the line above)

# [text](target "title") and ![alt](target), the target without spaces.
_INLINE = re.compile(r"(!?\[(?:[^\[\]]|\[[^\]]*\])*\]\()(<[^>]*>|[^)\s]+)((?:\s+\"[^\"]*\")?\))")
# [label]: target   (a reference definition, at the start of a line)
_REFERENCE = re.compile(r"^( {0,3}\[[^\]]+\]:\s*)(\S+)", re.MULTILINE)
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.DOTALL)


def _is_relative(target: str) -> bool:
    return not (
        not target
        or target.startswith(("#", "/", "mailto:", "data:"))
        or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)
    )


def _rewrite(target: str, page_uri: str, source: str, files) -> str:
    bracketed = target.startswith("<") and target.endswith(">")
    raw = target[1:-1] if bracketed else target
    if not _is_relative(raw):
        return target
    path, hash_, anchor = raw.partition("#")
    repo_path = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
    if repo_path.startswith(".."):
        return target  # outside the repository: not ours to resolve

    uri = layout.uri_of(repo_path)
    if uri is not None:
        file = files.get_file_from_path(uri)
        if file is not None and not file.inclusion.is_excluded():
            new = posixpath.relpath(uri, posixpath.dirname(page_uri) or ".")
            return new + hash_ + anchor
    if (layout.REPO / repo_path).exists():
        return layout.github_url(repo_path) + hash_ + anchor
    return target


def _rewrite_text(text: str, page_uri: str, source: str, files) -> str:
    """Rewrite the links of a stretch of Markdown that holds no fenced code."""
    spans: list[str] = []

    def keep_span(match: re.Match) -> str:
        spans.append(match.group(0))
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE_SPAN.sub(keep_span, text)
    text = _INLINE.sub(lambda m: m.group(1) + _rewrite(m.group(2), page_uri, source, files) + m.group(3), text)
    text = _REFERENCE.sub(lambda m: m.group(1) + _rewrite(m.group(2), page_uri, source, files), text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def on_files(files, config):
    """Keep literate-nav's nav files (SUMMARY.md) off the site.

    ``exclude_docs`` cannot: it is applied before mkdocs-gen-files adds the
    generated ones. Excluded, they are still read for the nav, but not published.
    """
    from mkdocs.structure.files import InclusionLevel

    for file in files:
        if file.src_uri.rsplit("/", 1)[-1] == "SUMMARY.md":
            file.inclusion = InclusionLevel.EXCLUDED
    return files


def on_page_markdown(markdown: str, page, config, files) -> str:
    source = layout.source_of(page.file.src_uri)
    if source is None:
        return markdown  # generated from code, no relative links of its own
    out: list[str] = []
    chunk: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines(keepends=True):
        match = _FENCE.match(line)
        if fence is None:
            if match:
                out.append(_rewrite_text("".join(chunk), page.file.src_uri, source, files))
                chunk = []
                fence = match.group(1)
                out.append(line)
            else:
                chunk.append(line)
        else:
            out.append(line)
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                fence = None
    out.append(_rewrite_text("".join(chunk), page.file.src_uri, source, files))
    return "".join(out)
