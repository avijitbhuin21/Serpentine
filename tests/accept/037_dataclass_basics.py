"""Dataclass basics: construction, field access, methods, ==, repr."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass


@dataclass
class Point:
    x: int
    y: int

    def norm2(self: Ref[Point]) -> int:
        return self.x * self.x + self.y * self.y

    def shift(self: Mut[Point], dx: int, dy: int) -> None:
        self.x += dx
        self.y += dy


def main() -> None:
    p: Point = Point(3, 4)
    print(p)
    print(p.x, p.y)
    print(p.norm2())
    p.shift(1, -1)
    print(p)
    print(p == Point(4, 3))
    print(p == Point(0, 0))
    q: Point = Point(4, 3)
    print(p == q)


if __name__ == "__main__":
    main()
