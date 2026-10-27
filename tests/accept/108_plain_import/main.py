"""Plain `import m`, `import pkg.mod` and `import pkg.mod as alias`: functions, classes
(constructors and annotations) and module-level constants reached through attributes."""
from __future__ import annotations

import geomlib
import shapes.area
import shapes.area as ar
from serpentine import Ref


def describe(p: Ref[geomlib.Point]) -> str:
    return f"({p.x}, {p.y}) |{p.norm1()}|"


def main() -> None:
    p: geomlib.Point = geomlib.Point(2, -5)
    print(describe(p))
    q: geomlib.Point = geomlib.scaled(p)
    print(describe(q), geomlib.SCALE)
    print(shapes.area.rect(3, 4), ar.rect(5, 6))
    print(ar.label("box", shapes.area.rect(q.x, 2)))
    pts: list[geomlib.Point] = [geomlib.Point(i, i * i) for i in range(4)]
    print(sum([pt.norm1() for pt in pts]))


if __name__ == "__main__":
    main()
