from __future__ import annotations


def rect(w: int, h: int) -> int:
    """Rectangle area."""
    return w * h


def label(name: str, area: int) -> str:
    """Pretty area line."""
    return f"{name}: {area}"
