"""Module-level type aliases, including Annotated aliases carrying Field metadata."""

from __future__ import annotations

from typing import Annotated

from serpentine import Field, Ref, dataclass, fields_json

Pair = tuple[int, int]
Names = list[str]
MaybeInt = int | None
PositiveInt = Annotated[int, Field(gt=0)]
Grid = dict[str, Pair]
Tight = Annotated[PositiveInt, Field(le=10)]


@dataclass
class Row:
    at: Pair
    tags: Names
    qty: PositiveInt = 1
    note: MaybeInt = None


@dataclass
class Cell:
    lim: Tight = 5


def total(p: Pair) -> int:
    return p[0] + p[1]


def label(g: Ref[Grid], key: str) -> str:
    got: Pair = g[key]
    return f"{key}={got[0]},{got[1]}"


def main() -> None:
    r = Row(at=(1, 2), tags=["a", "b"], qty=3, note=None)
    print(r.at, r.tags, r.qty, r.note)
    print(total(r.at))
    grid: Grid = {"o": (0, 0), "p": (4, 5)}
    print(label(grid, "p"))
    print(fields_json(Row))
    c = Cell(lim=9)
    print(c.lim)
    vals: Names = []
    for t in r.tags:
        vals.append(t.upper())
    print(vals)


if __name__ == "__main__":
    main()
