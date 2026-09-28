"""A live non-Copy variable passed to a `Ref[union]` parameter is borrowed, not moved.

Regression: both backends built the union temporary by moving the place into it
(rustc E0505 on Backend A; Backend B silently freed the caller's value).
"""
from __future__ import annotations

from serpentine import Ref, dataclass, move


@dataclass
class Vec:
    xs: list[float]

    def __mul__(self: Ref[Vec], other: Ref[float | Vec]) -> Vec:
        out: list[float] = []
        if isinstance(other, Vec):
            i: int = 0
            for v in self.xs:
                out.append(v * other.xs[i])
                i = i + 1
        else:
            k: float = float(other)
            for v in self.xs:
                out.append(v * k)
        return Vec(move(out))


@dataclass
class Box:
    inner: Vec


def total(v: Ref[float | Vec]) -> float:
    """Sum a union operand without taking ownership of it."""
    if isinstance(v, Vec):
        t: float = 0.0
        for x in v.xs:
            t = t + x
        return t
    return float(v)


def main() -> None:
    a: Vec = Vec([1.0, 2.0, 3.0])
    print((a * a).xs)
    print((a * 2).xs)
    print(a.xs)
    print(total(a), total(2.5), total(4))
    print(a.xs)
    b: Box = Box(Vec([5.0, 6.0]))
    print(total(b.inner))
    print(b.inner.xs)
    vs: list[Vec] = [Vec([1.5]), Vec([2.5])]
    print(total(vs[1]))
    print(vs[1].xs, len(vs))


if __name__ == "__main__":
    main()
