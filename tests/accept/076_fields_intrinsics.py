"""Field-table intrinsics: dump, schema and build over scalars, containers and nesting."""

from __future__ import annotations

from serpentine import (PyVal, Ref, dataclass, fields_build, fields_json, fields_of,
                        move, pyval_kind)


@dataclass
class Point:
    x: int
    y: int = 0


@dataclass
class Shape:
    name: str
    origin: Point
    scale: float
    closed: bool
    labels: list[str]
    corners: list[Point]
    meta: dict[str, int]
    blob: bytes
    tint: str | None
    span: tuple[int, str]
    payload: PyVal
    note: str = "plain"
    reps: list[int] = []


def dump_keys(s: Ref[Shape]) -> None:
    """Print every field of a shape in declaration order."""
    d = fields_of(s)
    for k, v in d.items():
        print(k, "=", v)


def main() -> None:
    p = Point(x=1, y=2)
    c = Point(x=3)
    s = Shape(name="box", origin=move(p), scale=1.5, closed=True, labels=["a"],
              corners=[move(c)], meta={"n": 4}, blob=b"hi", tint=None,
              span=(7, "z"), payload=None)
    dump_keys(s)
    print(fields_json(Point))
    src: dict[str, PyVal] = {"name": "disc", "origin": {"x": 5, "y": 6},
                             "scale": 2, "closed": False, "labels": ["b", "c"],
                             "corners": [{"x": 8}], "meta": {"m": 9},
                             "blob": b"ok", "tint": "red", "span": [1, "q"],
                             "payload": [1, 2], "reps": [3]}
    t = fields_build(Shape, src)
    print(t.name, t.origin.x, t.origin.y, t.scale, t.closed, t.note)
    print(t.corners[0].x, t.corners[0].y, t.tint, t.span[1], t.reps)
    print(fields_of(t))
    print(pyval_kind(t.payload))
    try:
        bad = fields_build(Point, {"x": "no"})
        print("unreachable", bad.x)
    except TypeError as e:
        print("rejected:", e)
    try:
        gap = fields_build(Point, {"y": 1})
        print("unreachable", gap.x)
    except TypeError as e:
        print("rejected:", e)


if __name__ == "__main__":
    main()
