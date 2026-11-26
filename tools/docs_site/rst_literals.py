"""A griffe extension: turn reStructuredText literal blocks in docstrings into fenced code.

The docstrings here are Google style, but many show an example the RST way::

    FrameStatsModule().run_one(frame).result

A paragraph ending in ``::`` and an indented block after it. Sphinx renders that
as code; Markdown, which is what mkdocstrings renders a docstring as, shows it as
running text. Rather than rewrite every docstring for one renderer, this rewrites
each block as it is loaded (``text::`` becomes ``text:``, a lone ``::`` goes, and
the block is fenced), so source and site both read well. Double-backtick spans
need nothing: Markdown reads them as code too.

Loaded by mkdocstrings (``extensions:`` in ``mkdocs.yml``); the source is untouched.
"""

from __future__ import annotations

import re
import textwrap

from griffe import Extension, Object

_OPENER = re.compile(r"^(?P<indent>\s*)(?P<text>.*?)::\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _language(block: list[str]) -> str:
    first = next((line.strip() for line in block if line.strip()), "")
    if first.startswith(("uv ", "$ ", "docker ", "kubectl ", "git ", "curl ")):
        return "shell"
    if first.startswith("[") and first.endswith("]"):
        return "toml"
    return "python"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def convert(text: str) -> str:
    """``text`` with every RST literal block fenced; anything else left as it was."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    in_fence = False
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _OPENER.match(line)
        if match is None:
            out.append(line)
            i += 1
            continue
        base = len(match["indent"])
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        block_end = j
        while block_end < len(lines) and (not lines[block_end].strip() or _indent(lines[block_end]) > base):
            block_end += 1
        block = lines[j:block_end]
        while block and not block[-1].strip():
            block.pop()
        if not block:  # a "::" with nothing indented after it: not a literal block
            out.append(line)
            i += 1
            continue
        lead = match["text"].rstrip()
        if lead:
            # "Example::" reads "Example:"; "the call ::" (a space before) drops the colons.
            out.append(match["indent"] + (lead if lead.endswith(" ") or line.rstrip().endswith(" ::") else lead + ":"))
            out.append("")
        pad = " " * base
        out.append(f"{pad}```{_language(block)}")
        out.extend(pad + code if code.strip() else "" for code in textwrap.dedent("\n".join(block)).splitlines())
        out.append(f"{pad}```")
        if block_end < len(lines):
            out.append("")
        i = block_end
    return "\n".join(out)


class RstLiterals(Extension):
    """Fence each docstring's RST literal blocks as it is loaded."""

    def on_instance(self, *, obj: Object, **kwargs) -> None:
        if obj.docstring is not None and "::" in obj.docstring.value:
            obj.docstring.value = convert(obj.docstring.value)
