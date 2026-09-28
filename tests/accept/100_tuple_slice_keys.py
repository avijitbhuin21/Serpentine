"""D43: tuple and slice keys reach __getitem__/__setitem__ (x[a, b] -> two arguments,
x[a:b] -> slice(a, b, None)); non-Copy tuple destructuring in for-loops over user
iterators; repr() escapes control characters like CPython."""
from __future__ import annotations
from typing import overload
from serpentine import Mut, Ref, dataclass, move, pyval_kind


@dataclass
class Grid:
    rows: list[list[int]]

    @overload
    def __getitem__(self: Ref[Grid], r: int, c: int) -> int: ...

    @overload
    def __getitem__(self: Ref[Grid], r: int) -> list[int]: ...

    @overload
    def __getitem__(self: Ref[Grid], r: Ref[slice]) -> Grid: ...

    def __getitem__(self: Ref[Grid], r: Ref[int | slice], c: int = -1) -> int | list[int] | Grid:
        if isinstance(r, slice):
            lo: int = 0
            hi: int = len(self.rows)
            if pyval_kind(r.start) != "NoneType":
                lo = int(r.start)
            if pyval_kind(r.stop) != "NoneType":
                hi = int(r.stop)
            if lo < 0:
                lo = len(self.rows) + lo
            if hi < 0:
                hi = len(self.rows) + hi
            out: list[list[int]] = []
            for i in range(lo, hi):
                out.append([v for v in self.rows[i]])
            return Grid(move(out))
        if isinstance(r, int):
            if c >= 0:
                return self.rows[r][c]
            return [v for v in self.rows[r]]
        return 0

    def __setitem__(self: Mut[Grid], r: int, c: int, v: int) -> None:
        self.rows[r][c] = v


@dataclass
class Named:
    keys: list[str]
    vals: list[list[int]]
    i: int

    def __iter__(self: Ref[Named]) -> Named:
        return self

    def __next__(self: Mut[Named]) -> tuple[str, list[int]]:
        if self.i >= len(self.keys):
            raise StopIteration()
        k: str = self.keys[self.i]
        xs: list[int] = [v for v in self.vals[self.i]]
        self.i += 1
        return (k, move(xs))


def main() -> None:
    g: Grid = Grid([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    print(g[1, 2], g[0], g[2, 0] + g[0, 2])
    print(g[1:3].rows, g[:2].rows, g[1:].rows, g[:].rows, g[-2:-1].rows)
    g[2, 0] = 70
    print(g[2], g[2, 0])
    sub: Grid = g[0:2]
    sub[0, 0] = -1
    print(sub.rows, g[0])
    it: Named = Named(["a", "bb"], [[1], [2, 3]], 0)
    for name, xs in it:
        xs.append(len(name))
        print(name, xs)
    total: int = 0
    for _n, ys in Named(["p", "q", "r"], [[1], [2], [3]], 0):
        total += ys[0]
    print(total)
    a: str = "a\x01b\x7fc"
    b: str = "tab\t\x00nul"
    c: str = "\x1b[0m"
    print(f"{a!r} {b!r} {c!r}", ["x\x02"])


if __name__ == "__main__":
    main()
