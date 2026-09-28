# serp-reject: SE002 missing-move
"""Reject: a live non-Copy value passed through a Callable needs an explicit move()."""

from serpentine import Callable, Owned, dataclass, move


@dataclass
class Point:
    x: int
    y: int


def flip(p: Owned[Point]) -> Point:
    return Point(p.y, p.x)


def apply_pt(f: Callable[[Point], Point], p: Owned[Point]) -> Point:
    return f(p)  # E: SE002


def main() -> None:
    a: Point = Point(1, 2)
    b: Point = apply_pt(flip, move(a))
    print(b.x, b.y)


if __name__ == "__main__":
    main()
