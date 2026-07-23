"""Operator overloading: arithmetic, neg, ordering, getitem/setitem/len."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass


@dataclass
class Vec2:
    x: float
    y: float

    def __add__(self: Ref[Vec2], other: Ref[Vec2]) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self: Ref[Vec2], other: Ref[Vec2]) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self: Ref[Vec2], k: float) -> Vec2:
        return Vec2(self.x * k, self.y * k)

    def __neg__(self: Ref[Vec2]) -> Vec2:
        return Vec2(-self.x, -self.y)

    def __getitem__(self: Ref[Vec2], i: int) -> float:
        if i == 0:
            return self.x
        if i == 1:
            return self.y
        raise IndexError("Vec2 index out of range")

    def __setitem__(self: Mut[Vec2], i: int, v: float) -> None:
        if i == 0:
            self.x = v
        elif i == 1:
            self.y = v
        else:
            raise IndexError("Vec2 index out of range")

    def __len__(self: Ref[Vec2]) -> int:
        return 2

    def __lt__(self: Ref[Vec2], other: Ref[Vec2]) -> bool:
        return self.x * self.x + self.y * self.y < other.x * other.x + other.y * other.y


def main() -> None:
    a: Vec2 = Vec2(1.0, 2.0)
    b: Vec2 = Vec2(3.0, 4.0)
    c: Vec2 = a + b
    print(c)
    print(a - b)
    print(a * 2.5)
    print(-a)
    print(a + b * 2.0)
    print(a[0], a[1])
    d: Vec2 = Vec2(0.0, 0.0)
    d[0] = 7.5
    d[1] = -1.5
    print(d)
    print(len(d))
    print(a < b, b < a)
    print(a == Vec2(1.0, 2.0))
    try:
        print(a[5])
    except IndexError as e:
        print("caught:", e)


if __name__ == "__main__":
    main()
