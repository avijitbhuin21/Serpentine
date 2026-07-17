# serp-reject: SE004 conflicting-borrow
"""Reject: mutating through a per-iteration Ref loop variable (rustc parity)."""
from __future__ import annotations
from serpentine import dataclass


@dataclass
class Cell:
    val: int


def main() -> None:
    cells: list[Cell] = [Cell(1), Cell(2)]
    for c in cells:
        c.val = 0  # E: SE004
    print(len(cells))


if __name__ == "__main__":
    main()
