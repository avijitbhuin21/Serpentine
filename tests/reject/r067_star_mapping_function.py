# serp-reject: SE201 unsupported-feature
"""Reject: a runtime mapping can only be **unpacked into a class constructor."""

from __future__ import annotations

from serpentine import PyVal


def show(a: int, b: int) -> None:
    """Print two arguments."""
    print(a, b)


def main() -> None:
    d: dict[str, PyVal] = {"a": 1, "b": 2}
    show(**d)  # E: SE201


if __name__ == "__main__":
    main()
