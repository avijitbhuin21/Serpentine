"""Checker-as-library API (docs/archive/research.md §5.13): structured diagnostics for tooling.

This is the supported programmatic surface for editors, CI hooks, and the LSP
server. It never prints and never exits; it returns `Diagnostic` values.
"""

from pathlib import Path

from .cli import run_check
from .diagnostics import Diagnostic, Reporter, SerpError


def check_file(path: str | Path, overlay: dict[str, str] | None = None) -> list[Diagnostic]:
    """Check the program rooted at `path`; return all diagnostics (empty = clean).

    `overlay` maps resolved file paths to in-memory contents that shadow the
    on-disk text, so unsaved editor buffers can be checked.
    """
    rep = Reporter()
    try:
        run_check(Path(path), rep, overlay=overlay)
    except SerpError:
        pass
    return list(rep.diags)


def check_source(path: str | Path, text: str) -> list[Diagnostic]:
    """Check a single in-memory buffer as the program entry point."""
    resolved = str(Path(path).resolve())
    return check_file(path, overlay={resolved: text})
