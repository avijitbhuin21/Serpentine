"""D40: @overload-typed __getitem__ — the call site takes the overload's return type
(a union member), so one indexer can yield a cell for a label and a container for a mask."""
from __future__ import annotations
from typing import overload
from serpentine import Ref, Mut, dataclass, PyVal, pyval_kind, move


@dataclass
class Vec:
    xs: list[int]

    @overload
    def __getitem__(self: Ref[Vec], key: int) -> int: ...

    @overload
    def __getitem__(self: Ref[Vec], key: Ref[list[bool]]) -> Vec: ...

    def __getitem__(self: Ref[Vec], key: Ref[int | list[bool]]) -> int | Vec:
        if isinstance(key, int):
            return self.xs[key]
        return Vec([self.xs[i] for i in range(len(self.xs)) if key[i]])

    def __gt__(self: Ref[Vec], k: int) -> list[bool]:
        return [x > k for x in self.xs]

    def total(self: Ref[Vec]) -> int:
        return sum(self.xs)


@dataclass
class Table:
    cols: dict[str, list[PyVal]]
    names: list[str]

    @overload
    def __getitem__(self: Ref[Table], key: str) -> list[PyVal]: ...

    @overload
    def __getitem__(self: Ref[Table], key: Ref[list[str]]) -> Table: ...

    def __getitem__(self: Ref[Table], key: Ref[str | list[str]]) -> list[PyVal] | Table:
        if isinstance(key, str):
            return [v for v in self.cols[key]]
        out: dict[str, list[PyVal]] = {}
        for k in key:
            out[k] = [v for v in self.cols[k]]
        return Table(move(out), [k for k in key])


def main() -> None:
    v: Vec = Vec([5, 1, 7, 3])
    n: int = v[2]
    big: Vec = v[v > 2]
    print(n, v[0] + v[1], big.xs, big.total(), v[v > 100].xs)
    print(v[[True, False, True, False]].xs, len(v[v > 4].xs))
    t: Table = Table({"a": [1, 2], "b": ["x", "y"], "c": [1.5, 2.5]}, ["a", "b", "c"])
    col: list[PyVal] = t["b"]
    sub: Table = t[["a", "c"]]
    print(col, t["a"], sub.names, sub["c"], t[["b"]].names)
    print(pyval_kind(t["c"][0]))


if __name__ == "__main__":
    main()
