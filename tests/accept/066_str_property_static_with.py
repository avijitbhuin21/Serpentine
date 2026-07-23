"""Tier-2 protocol forms: __str__, @property, @staticmethod, with on user objects."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass, move


@dataclass
class Point:
    x: int
    y: int

    def __str__(self: Ref[Point]) -> str:
        return f"({self.x}, {self.y})"

    @property
    def norm2(self: Ref[Point]) -> int:
        return self.x * self.x + self.y * self.y

    @staticmethod
    def origin() -> Point:
        return Point(0, 0)

    @staticmethod
    def of(v: int) -> Point:
        return Point(v, v)


@dataclass
class Box:
    items: list[int]
    closed: bool

    def add(self: Mut[Box], v: int) -> None:
        self.items.append(v)

    def __enter__(self: Ref[Box]) -> Box:
        return self

    def __exit__(self: Mut[Box], exc_type: None, exc: None, tb: None) -> None:
        self.closed = True
        print("box closed with", len(self.items), "items")


def main() -> None:
    p: Point = Point(3, 4)
    print(p)
    print(str(p))
    s: str = f"point={p}!"
    print(s)
    print(p.norm2)
    print(Point(1, 2).norm2)
    print(Point.origin())
    q: Point = Point.of(7)
    print(q, q.norm2)
    empty: list[int] = []
    with Box(move(empty), False) as b:
        b.add(1)
        b.add(2)
        print("inside", len(b.items))
    print(b.closed)
    try:
        empty2: list[int] = []
        with Box(move(empty2), False) as c:
            c.add(5)
            raise ValueError("boom")
    except ValueError as e:
        print("caught:", e)
    print(c.closed)


if __name__ == "__main__":
    main()
