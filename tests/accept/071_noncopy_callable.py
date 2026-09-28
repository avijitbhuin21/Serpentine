from __future__ import annotations

from serpentine import Callable, Owned, dataclass, move


@dataclass
class Point:
    x: int
    y: int


def flip(p: Owned[Point]) -> Point:
    return Point(p.y, p.x)


def stretch(p: Owned[Point]) -> Point:
    return Point(p.x * 10, p.y * 10)


def apply_pt(f: Callable[[Point], Point], p: Owned[Point]) -> Point:
    return f(move(p))


def make_pts(n: int) -> list[Point]:
    out: list[Point] = []
    for i in range(n):
        out.append(Point(i, i + 1))
    return out


def transform(f: Callable[[int], list[Point]]) -> int:
    pts: list[Point] = f(3)
    return len(pts)


def main() -> None:
    a: Point = Point(1, 2)
    b: Point = apply_pt(flip, move(a))
    print(b.x, b.y)
    c: Point = apply_pt(stretch, move(b))
    print(c.x, c.y)
    print(transform(make_pts))


if __name__ == "__main__":
    main()
