"""Console output: sections, pass/fail lines, and a summary that counts failures.

A :class:`Report` is how a multi-step command keeps the "every check runs, the
command fails if any did" rule: each step reports into it, nothing aborts the
run, and :meth:`Report.finish` prints the summary and returns the exit code.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from rich.console import Console
from rich.markup import escape


def _utf8_streams() -> None:
    """Make stdout/stderr UTF-8 so ``✓``/``✗`` never crash a Windows pipe (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None and (stream.encoding or "").lower().replace("-", "") != "utf8":
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


_utf8_streams()
console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)


def section(title: str) -> None:
    console.print(f"\n[bold]==> {escape(title)}[/bold]")


def ok(label: str) -> None:
    console.print(f"  [green]✓[/green] {escape(label)}")


def bad(label: str, detail: str = "") -> None:
    suffix = f" [dim]-- {escape(detail)}[/dim]" if detail else ""
    console.print(f"  [red]✗[/red] {escape(label)}{suffix}")


def info(message: str) -> None:
    console.print(f"    {message}", markup=False)


def error(message: str) -> None:
    """A fatal, user-facing error (no traceback): red on stderr."""
    err_console.print(f"[red]error:[/red] {escape(message)}")


@dataclass
class Report:
    """Collects the outcome of every step of a command."""

    failures: list[str] = field(default_factory=list)

    def record(self, label: str, passed: bool, detail: str = "") -> bool:
        if passed:
            ok(label)
        else:
            bad(label, detail)
            self.failures.append(label)
        return passed

    def step(self, label: str, action: Callable[[], int | bool]) -> bool:
        """Run ``action`` (an exit code or a bool) and record it; an exception is a failure, not a crash."""
        try:
            result = action()
        except Exception as exc:  # noqa: BLE001 — every step must run; report and move on
            return self.record(label, False, f"{type(exc).__name__}: {exc}")
        passed = result == 0 if not isinstance(result, bool) else result
        return self.record(label, passed)

    def finish(self, success: str, failure_hint: str = "") -> int:
        section("Summary")
        if not self.failures:
            console.print(f"[green]{success}[/green]")
            return 0
        console.print(f"[red]{len(self.failures)} check(s) failed:[/red]")
        for label in self.failures:
            console.print(f"  - {label}")
        if failure_hint:
            console.print(f"\n{failure_hint}")
        return 1
