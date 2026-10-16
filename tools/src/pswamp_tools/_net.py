"""Polling a URL and opening a browser, without curl, xdg-open or open.

``answers`` uses a short *connect* timeout on purpose: an unroutable address
(a minikube node IP on macOS/Windows) drops packets rather than refusing, so
without one every attempt would sit for its full timeout and a fallback would
start only after a silent minute, which reads as a hang. A refused or answered
connection returns at once either way.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import _ui


def answers(url: str, connect_timeout: float = 1.0, timeout: float = 2.0) -> bool:
    """True if a GET of ``url`` returns a 2xx within the timeouts."""
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # Connect first with the short timeout; only a host that accepts gets the longer one.
    try:
        socket.create_connection((parsed.hostname or "localhost", port), timeout=connect_timeout).close()
    except OSError:
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_until_answers(url: str, attempts: int, interval: float = 0.5, dots: bool = True) -> bool:
    """Poll ``url`` up to ``attempts`` times; a dot per failed attempt so a wait never looks wedged."""
    for _ in range(attempts):
        if answers(url):
            if dots:
                _ui.console.print()
            return True
        if dots:
            _ui.console.print(".", end="")
        time.sleep(interval)
    if dots:
        _ui.console.print()
    return False


def open_browser(url: str) -> None:
    """Hand ``url`` to the platform's browser; say so when there is none (e.g. over SSH)."""
    try:
        opened = webbrowser.open(url)
    except webbrowser.Error:
        opened = False
    if not opened:
        _ui.info(f"Could not open a browser; open {url} manually.")
