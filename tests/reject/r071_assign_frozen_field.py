# serp-reject: SE201 unsupported-feature
"""Reject: a field of a frozen class cannot be assigned after construction."""

from __future__ import annotations

from serpentine import dataclass


@dataclass(frozen=True)
class Point:
    x: int
    y: int


def main() -> None:
    p = Point(x=1, y=2)
    p.x = 5  # E: SE201
    print(p.x + p.y)


if __name__ == "__main__":
    main()
