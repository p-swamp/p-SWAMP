"""The project's contributors, as GitHub lists them, for the Contributors page.

Read from the GitHub API at build time (``/repos/<repo>/contributors``, then
each person's display name), so the page follows the repository with no list
to maintain by hand. Bots are left out.

A build must not depend on the network: with no answer (offline, rate-limited,
the repository not reachable), ``fetch`` returns ``None`` and the page links to
GitHub's own list instead. ``GITHUB_TOKEN``, when set (CI sets it), lifts the
unauthenticated rate limit of 60 requests an hour. The answer is kept for the
life of the process, so `pswamp docs serve` asks once, not on every rebuild.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import cache

log = logging.getLogger("mkdocs.plugins.pswamp_docs")

API = "https://api.github.com"
TIMEOUT_S = 10


@dataclass(frozen=True)
class Contributor:
    login: str
    name: str
    profile: str
    avatar: str
    contributions: int


def _get(url: str):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "pswamp-docs"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


def _is_bot(entry: dict) -> bool:
    return entry.get("type") != "User" or entry.get("login", "").endswith("[bot]")


@cache
def fetch(repo: str) -> tuple[Contributor, ...] | None:
    """Every human contributor to ``repo`` (``owner/name``), most contributions first, or None."""
    try:
        entries = _get(f"{API}/repos/{repo}/contributors?per_page=100")
        people = []
        for entry in entries:
            if _is_bot(entry):
                continue
            try:
                name = _get(entry["url"]).get("name") or entry["login"]
            except (urllib.error.URLError, OSError, ValueError):
                name = entry["login"]
            people.append(
                Contributor(
                    login=entry["login"],
                    name=name,
                    profile=entry["html_url"],
                    avatar=entry["avatar_url"],
                    contributions=entry.get("contributions", 0),
                )
            )
        return tuple(people)
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        # Info, not a warning: --strict must not fail for want of a network.
        log.info(f"contributors: GitHub did not answer ({exc}); the page links to GitHub instead")
        return None
