# serp-reject: SE217 uninitialized-field
"""Reject: a user __init__ that leaves a field unassigned (definite assignment)."""
from __future__ import annotations
from serpentine import Mut, dataclass


@dataclass
class Point:
    x: int
    y: int

    def __init__(self: Mut[Point], x: int) -> None:  # E: SE217
        self.x = x


def main() -> None:
    p: Point = Point(1)
    print(p.x)


if __name__ == "__main__":
    main()
