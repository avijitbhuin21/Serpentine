"""Comprehensions with several `for` and `if` clauses (lowered to nested comprehensions)."""
from __future__ import annotations
from serpentine import dataclass


@dataclass
class Cell:
    r: int
    c: str


def main() -> None:
    rows: list[int] = [1, 2, 3]
    cols: list[str] = ["a", "b"]
    print([str(r) + c for r in rows for c in cols])
    print([str(r) + c for r in rows if r != 2 for c in cols if c != "a"])
    print([x for x in range(30) if x % 2 == 0 if x % 3 == 0])
    print([(r, k) for r in rows for k in range(r)])
    print([i + j + k for i in range(2) for j in range(2) for k in range(2)])
    grid: list[list[int]] = [[1, 2], [3], [], [4, 5, 6]]
    print([v * 10 for row in grid for v in row if v != 5])
    cells: list[Cell] = [Cell(r, c) for r in rows for c in cols]
    print(len(cells), cells[0], cells[5])
    print(sorted({a * b for a in rows for b in rows}))
    print({k: k * k for k in range(10) if k > 1 if k % 3 != 0})


if __name__ == "__main__":
    main()
