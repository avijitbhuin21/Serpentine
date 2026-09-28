"""`**mapping` unpacking at call sites: dict literals, PyVal mappings, cls(**data)."""
from __future__ import annotations

from typing import Self

from serpentine import PyVal, dataclass


@dataclass
class Point:
    x: int
    y: int = 5
    tag: str = "p"


@dataclass
class Row:
    a: int
    b: str = "z"

    @classmethod
    def of(cls, data: PyVal) -> Self:
        """Build a row from a mapping."""
        return cls(**data)


def show(a: int, b: int, c: str) -> None:
    """Print three arguments."""
    print(a, b, c)


def main() -> None:
    d: dict[str, PyVal] = {"x": 1, "y": 2, "tag": "hi"}
    p = Point(**d)
    print(p.x, p.y, p.tag)

    q = Point(**{"x": 9, "tag": "lit"})
    print(q.x, q.y, q.tag)

    show(**{"a": 1, "b": 2, "c": "z"})
    show(1, **{"b": 7, "c": "w"})

    partial: dict[str, PyVal] = {"x": 4}
    r = Point(**partial)
    print(r.x, r.y, r.tag)

    row = Row.of({"a": 3, "b": "q"})
    print(row.a, row.b)

    nested: dict[str, PyVal] = {"a": 8}
    row2 = Row.of(nested)
    print(row2.a, row2.b)


if __name__ == "__main__":
    main()
