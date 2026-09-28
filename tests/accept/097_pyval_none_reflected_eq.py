"""PyVal `is None` / `is not None` on parameters, locals and cells; method args that read
the mutably-borrowed receiver; reflected operators and __eq__/__ne__ overloads on classes."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass, PyVal, pyval_kind


def describe(v: PyVal) -> str:
    if v is None:
        return "none"
    if v is not None and pyval_kind(v) == "int":
        return "int"
    return "other"


@dataclass
class Col:
    xs: list[int]

    def __eq__(self: Ref[Col], k: int) -> list[bool]:
        return [x == k for x in self.xs]

    def __ne__(self: Ref[Col], k: int) -> list[bool]:
        return [x != k for x in self.xs]

    def __radd__(self: Ref[Col], k: int) -> Col:
        return Col([k + x for x in self.xs])

    def __rmul__(self: Ref[Col], k: int) -> Col:
        return Col([k * x for x in self.xs])

    def __rsub__(self: Ref[Col], k: int) -> Col:
        return Col([k - x for x in self.xs])

    def __rtruediv__(self: Ref[Col], k: float) -> list[float]:
        return [k / x for x in self.xs]


def main() -> None:
    a: PyVal = None
    b: PyVal = 3
    print(describe(a), describe(b), describe("s"))
    cells: list[PyVal] = [1, None, "x"]
    for c in cells:
        print(c is None, c is not None)
    c1: PyVal = cells[1]
    c0: PyVal = cells[0]
    print(c1 is None, c0 is None)
    xs: list[int] = [1, 2]
    xs.append(len(xs))
    xs.append(xs[0] + xs[2])
    print(xs)
    d: dict[str, int] = {"a": 1}
    d["b"] = len(d)
    print(d)
    col: Col = Col([1, 2, 3])
    print(col == 2, col != 2)
    print((10 + col).xs, (2 * col).xs, (10 - col).xs, 6.0 / col)
    print((Col([1]) == 1)[0])


if __name__ == "__main__":
    main()
