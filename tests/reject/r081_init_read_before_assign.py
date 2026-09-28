# serp-reject: SE217 uninitialized-field
"""Reject: reading a field in __init__ before it has been assigned."""
from __future__ import annotations
from serpentine import Mut, dataclass


@dataclass
class Box:
    width: int
    area: int

    def __init__(self: Mut[Box], width: int) -> None:
        self.area = self.width * 2  # E: SE217
        self.width = width


def main() -> None:
    b: Box = Box(3)
    print(b.area)


if __name__ == "__main__":
    main()
