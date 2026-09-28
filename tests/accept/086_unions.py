"""Accept: union types (int | str, Union[...]), isinstance narrowing (LB5)."""

from __future__ import annotations

from enum import Enum
from typing import Union

from serpentine import Mut, Ref, dataclass


class Color(Enum):
    RED = "red"
    BLUE = "blue"


@dataclass
class Point:
    x: int
    y: int


@dataclass
class Cell:
    tag: str
    val: int | list[int]


def kind(v: Ref[int | str | Point]) -> str:
    """Describe a three-member union by testing each runtime kind."""
    if isinstance(v, int):
        return f"int:{v}"
    if isinstance(v, str):
        return f"str:{v}"
    if isinstance(v, Point):
        return f"point:{v.x},{v.y}"
    return "?"


def pick(flag: bool) -> Union[int, str]:
    """Return either member of a union."""
    if flag:
        return 3
    return "three"


def cell_sum(c: Ref[Cell]) -> int:
    """Narrow a union-typed field."""
    if isinstance(c.val, int):
        return c.val
    return sum(c.val)


def bump(c: Mut[Cell]) -> None:
    """Overwrite a union field with the other member."""
    c.val = [7, 8]


def tagged(v: str | Color) -> str:
    """Narrow a union whose members are a str and an enum."""
    if isinstance(v, Color):
        return f"color {v.value}"
    return f"plain {v}"


def maybe(v: int | str | None) -> str:
    """Narrow a union that includes None."""
    if v is None:
        return "none"
    if isinstance(v, int):
        return f"n{v}"
    if isinstance(v, str):
        return f"s{v}"
    return "?"


def scale(v: float | str) -> str:
    """Widen an int argument into the float member of a union."""
    if isinstance(v, float):
        return f"{v * 2.0}"
    return v.upper()


def total(items: Ref[list[int | str]]) -> int:
    """Sum the int members of a mixed list, counting strings by length."""
    n = 0
    for it in items:
        if isinstance(it, int):
            n = n + it
        if isinstance(it, str):
            n = n + len(it)
    return n


def main() -> None:
    """Exercise unions across arguments, returns, fields and containers."""
    print(kind(5), kind("hi"), kind(Point(1, 2)))
    print(pick(True), pick(False))
    print(cell_sum(Cell("a", 4)), cell_sum(Cell("b", [1, 2, 3])))
    c = Cell("c", 1)
    bump(c)
    print(c, cell_sum(c))
    print(tagged("x"), tagged(Color.BLUE))
    print(maybe(None), maybe(7), maybe("q"))
    print(scale(3.0), scale("hi"))
    d: dict[str, int | str] = {"a": 1, "b": "two"}
    print(d["a"], d["b"], d)
    vals: list[int | str] = [1, "two", 3]
    print(vals, total(vals))
    a: int | str = 5
    b: int | str = 5
    e: int | str = "5"
    print(a == b, a == e, a != e)
    a = "now a str"
    if isinstance(a, str):
        print(a.upper())


if __name__ == "__main__":
    main()
