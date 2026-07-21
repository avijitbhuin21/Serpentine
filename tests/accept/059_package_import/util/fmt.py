"""Formatting helpers for the package-import accept test."""


def rule(n: int) -> str:
    out: str = ""
    i: int = 0
    while i < n:
        out = out + "-"
        i = i + 1
    return out
