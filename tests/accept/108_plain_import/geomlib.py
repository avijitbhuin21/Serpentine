from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Point:
    x: int
    y: int

    def norm1(self: Ref[Point]) -> int:
        return abs(self.x) + abs(self.y)


SCALE: int = 3


def scaled(p: Ref[Point]) -> Point:
    """A copy of p multiplied by SCALE."""
    return Point(p.x * SCALE, p.y * SCALE)
