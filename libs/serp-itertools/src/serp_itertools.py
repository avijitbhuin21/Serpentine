"""serp-itertools — drop-in facade for CPython's `itertools` in the Serpentine subset.

Pure Serpentine ([P]). Iterators are real lazy objects (classes with
`__iter__`/`__next__`) so `count()` and `cycle()` are genuinely infinite and
`next()` works on every returned iterator. Inputs are lists (the subset's
iterable); element types must be Copy so values can be copied out of the
borrowed input.

Documented divergences from CPython (see README):
- inputs are `list[T]`, not arbitrary iterables; `chain`/`product`/`zip_longest`
  take exactly two inputs of the same element type.
- `permutations`/`combinations`/`combinations_with_replacement`/`batched` yield
  `list[T]` rows, not tuples.
- `repeat(x, times)` uses `times=-1` as the "not given" sentinel (infinite);
  `islice` uses `stop=-2` for the one-argument form and `stop=-1` for `None`.
- `accumulate` supports plain addition only; `zip_longest` requires `fillvalue`.
- `starmap`, `groupby` and `tee` are not provided.
"""
from __future__ import annotations
from serpentine import Callable, Generic, Mut, Ref, TypeVar, dataclass, move

T = TypeVar("T")


def _copy(xs: Ref[list[T]]) -> list[T]:
    """Copy a borrowed list of Copy elements into a fresh owned list."""
    out: list[T] = []
    for i in range(len(xs)):
        out.append(xs[i])
    return out


@dataclass
class _Count:
    cur: int
    step: int

    def __iter__(self: Ref[_Count]) -> _Count:
        return self

    def __next__(self: Mut[_Count]) -> int:
        v: int = self.cur
        self.cur = self.cur + self.step
        return v


@dataclass
class _Cycle(Generic[T]):
    xs: list[T]
    i: int

    def __iter__(self: Ref[_Cycle[T]]) -> _Cycle[T]:
        return self

    def __next__(self: Mut[_Cycle[T]]) -> T:
        if len(self.xs) == 0:
            raise StopIteration()
        v: T = self.xs[self.i]
        self.i = (self.i + 1) % len(self.xs)
        return v


@dataclass
class _Repeat(Generic[T]):
    val: T
    times: int
    i: int

    def __iter__(self: Ref[_Repeat[T]]) -> _Repeat[T]:
        return self

    def __next__(self: Mut[_Repeat[T]]) -> T:
        if self.times >= 0 and self.i >= self.times:
            raise StopIteration()
        self.i += 1
        return self.val


@dataclass
class _Seq(Generic[T]):
    xs: list[T]
    i: int

    def __iter__(self: Ref[_Seq[T]]) -> _Seq[T]:
        return self

    def __next__(self: Mut[_Seq[T]]) -> T:
        if self.i >= len(self.xs):
            raise StopIteration()
        v: T = self.xs[self.i]
        self.i += 1
        return v


@dataclass
class _SeqTup(Generic[T]):
    items: list[tuple[T, T]]
    i: int

    def __iter__(self: Ref[_SeqTup[T]]) -> _SeqTup[T]:
        return self

    def __next__(self: Mut[_SeqTup[T]]) -> tuple[T, T]:
        if self.i >= len(self.items):
            raise StopIteration()
        v: tuple[T, T] = self.items[self.i]
        self.i += 1
        return v


@dataclass
class _SeqRows(Generic[T]):
    rows: list[list[T]]
    i: int

    def __iter__(self: Ref[_SeqRows[T]]) -> _SeqRows[T]:
        return self

    def __next__(self: Mut[_SeqRows[T]]) -> list[T]:
        if self.i >= len(self.rows):
            raise StopIteration()
        row: list[T] = []
        for j in range(len(self.rows[self.i])):
            row.append(self.rows[self.i][j])
        self.i += 1
        return row


@dataclass
class _TakeWhile(Generic[T]):
    xs: list[T]
    i: int
    pred: Callable[[T], bool]
    done: bool

    def __iter__(self: Ref[_TakeWhile[T]]) -> _TakeWhile[T]:
        return self

    def __next__(self: Mut[_TakeWhile[T]]) -> T:
        if self.done or self.i >= len(self.xs):
            raise StopIteration()
        v: T = self.xs[self.i]
        self.i += 1
        if self.pred(v):
            return v
        self.done = True
        raise StopIteration()


@dataclass
class _DropWhile(Generic[T]):
    xs: list[T]
    i: int
    pred: Callable[[T], bool]
    dropped: bool

    def __iter__(self: Ref[_DropWhile[T]]) -> _DropWhile[T]:
        return self

    def __next__(self: Mut[_DropWhile[T]]) -> T:
        while not self.dropped and self.i < len(self.xs):
            v0: T = self.xs[self.i]
            if self.pred(v0):
                self.i += 1
            else:
                self.dropped = True
        if self.i >= len(self.xs):
            raise StopIteration()
        v: T = self.xs[self.i]
        self.i += 1
        return v


@dataclass
class _FilterFalse(Generic[T]):
    xs: list[T]
    i: int
    pred: Callable[[T], bool]

    def __iter__(self: Ref[_FilterFalse[T]]) -> _FilterFalse[T]:
        return self

    def __next__(self: Mut[_FilterFalse[T]]) -> T:
        while self.i < len(self.xs):
            v: T = self.xs[self.i]
            self.i += 1
            if not self.pred(v):
                return v
        raise StopIteration()


def count(start: int = 0, step: int = 1) -> _Count:
    """count(start=0, step=1) — infinite arithmetic sequence of ints."""
    return _Count(start, step)


def cycle(iterable: Ref[list[T]]) -> _Cycle[T]:
    """cycle(iterable) — repeat the elements of a list endlessly."""
    buf: list[T] = _copy(iterable)
    return _Cycle(move(buf), 0)


def repeat(obj: T, times: int = -1) -> _Repeat[T]:
    """repeat(obj[, times]) — yield obj forever, or `times` times if given."""
    return _Repeat(obj, times, 0)


def chain(a: Ref[list[T]], b: Ref[list[T]]) -> _Seq[T]:
    """chain(a, b) — iterate a, then b (two-list form)."""
    buf: list[T] = _copy(a)
    for j in range(len(b)):
        buf.append(b[j])
    return _Seq(move(buf), 0)


def islice(iterable: Ref[list[T]], start: int, stop: int = -2, step: int = 1) -> _Seq[T]:
    """islice(xs, stop) or islice(xs, start, stop[, step]); stop=-1 means None."""
    s: int = start
    e: int = stop
    if stop == -2:
        s = 0
        e = start
    if e == -1:
        e = len(iterable)
    if s < 0 or e < 0:
        raise ValueError(
            "Indices for islice() must be None or an integer: 0 <= x <= sys.maxsize.")
    if step < 1:
        raise ValueError("Step for islice() must be a positive integer or None.")
    if e > len(iterable):
        e = len(iterable)
    buf: list[T] = []
    j: int = s
    while j < e:
        buf.append(iterable[j])
        j += step
    return _Seq(move(buf), 0)


def compress(data: Ref[list[T]], selectors: Ref[list[bool]]) -> _Seq[T]:
    """compress(data, selectors) — elements of data whose selector is True."""
    n: int = min(len(data), len(selectors))
    buf: list[T] = []
    for j in range(n):
        if selectors[j]:
            buf.append(data[j])
    return _Seq(move(buf), 0)


def accumulate(iterable: Ref[list[T]]) -> _Seq[T]:
    """accumulate(xs) — running totals using + (function form not supported)."""
    buf: list[T] = []
    if len(iterable) == 0:
        return _Seq(move(buf), 0)
    total: T = iterable[0]
    buf.append(total)
    for j in range(1, len(iterable)):
        total = total + iterable[j]
        buf.append(total)
    return _Seq(move(buf), 0)


def pairwise(iterable: Ref[list[T]]) -> _SeqTup[T]:
    """pairwise(xs) — successive overlapping pairs as tuples."""
    items: list[tuple[T, T]] = []
    for j in range(len(iterable) - 1):
        p: tuple[T, T] = (iterable[j], iterable[j + 1])
        items.append(p)
    return _SeqTup(move(items), 0)


def product(a: Ref[list[T]], b: Ref[list[T]]) -> _SeqTup[T]:
    """product(a, b) — cartesian product of two same-typed lists as tuples."""
    items: list[tuple[T, T]] = []
    for i in range(len(a)):
        for j in range(len(b)):
            p: tuple[T, T] = (a[i], b[j])
            items.append(p)
    return _SeqTup(move(items), 0)


def zip_longest(a: Ref[list[T]], b: Ref[list[T]], fillvalue: T) -> _SeqTup[T]:
    """zip_longest(a, b, fillvalue) — zip padding the shorter list with fillvalue."""
    n: int = max(len(a), len(b))
    items: list[tuple[T, T]] = []
    for j in range(n):
        va: T = fillvalue
        vb: T = fillvalue
        if j < len(a):
            va = a[j]
        if j < len(b):
            vb = b[j]
        p: tuple[T, T] = (va, vb)
        items.append(p)
    return _SeqTup(move(items), 0)


def takewhile(predicate: Callable[[T], bool], iterable: Ref[list[T]]) -> _TakeWhile[T]:
    """takewhile(pred, xs) — elements while pred(x) is true, then stop."""
    buf: list[T] = _copy(iterable)
    return _TakeWhile(move(buf), 0, predicate, False)


def dropwhile(predicate: Callable[[T], bool], iterable: Ref[list[T]]) -> _DropWhile[T]:
    """dropwhile(pred, xs) — skip elements while pred(x) is true, then yield the rest."""
    buf: list[T] = _copy(iterable)
    return _DropWhile(move(buf), 0, predicate, False)


def filterfalse(predicate: Callable[[T], bool], iterable: Ref[list[T]]) -> _FilterFalse[T]:
    """filterfalse(pred, xs) — elements where pred(x) is false."""
    buf: list[T] = _copy(iterable)
    return _FilterFalse(move(buf), 0, predicate)


def batched(iterable: Ref[list[T]], n: int) -> _SeqRows[T]:
    """batched(xs, n) — successive rows of length n (last may be shorter)."""
    if n < 1:
        raise ValueError("n must be at least one")
    rows: list[list[T]] = []
    cur: list[T] = []
    for j in range(len(iterable)):
        cur.append(iterable[j])
        if len(cur) == n:
            rows.append(move(cur))
            cur = []
    if len(cur) > 0:
        rows.append(move(cur))
    return _SeqRows(move(rows), 0)


def permutations(iterable: Ref[list[T]], r: int = -1) -> _SeqRows[T]:
    """permutations(xs[, r]) — r-length permutations in CPython order (as lists)."""
    n: int = len(iterable)
    k: int = r
    if k == -1:
        k = n
    if k < 0:
        raise ValueError("r must be non-negative")
    rows: list[list[T]] = []
    if k > n:
        return _SeqRows(move(rows), 0)
    indices: list[int] = []
    for j in range(n):
        indices.append(j)
    cycles: list[int] = []
    for j in range(k):
        cycles.append(n - j)
    first: list[T] = []
    for j in range(k):
        first.append(iterable[indices[j]])
    rows.append(move(first))
    if n == 0:
        return _SeqRows(move(rows), 0)
    running: bool = True
    while running:
        advanced: bool = False
        i2: int = 0
        while i2 < k:
            i: int = k - 1 - i2
            cnew: int = cycles[i] - 1
            cycles[i] = cnew
            if cycles[i] == 0:
                moved: int = indices[i]
                jj: int = i
                while jj < n - 1:
                    shifted: int = indices[jj + 1]
                    indices[jj] = shifted
                    jj += 1
                indices[n - 1] = moved
                cycles[i] = n - i
            else:
                j2: int = cycles[i]
                tmp: int = indices[i]
                swapped: int = indices[n - j2]
                indices[i] = swapped
                indices[n - j2] = tmp
                row: list[T] = []
                for j3 in range(k):
                    row.append(iterable[indices[j3]])
                rows.append(move(row))
                advanced = True
                break
            i2 += 1
        if not advanced:
            running = False
    return _SeqRows(move(rows), 0)


def combinations(iterable: Ref[list[T]], r: int) -> _SeqRows[T]:
    """combinations(xs, r) — r-length combinations in CPython order (as lists)."""
    n: int = len(iterable)
    if r < 0:
        raise ValueError("r must be non-negative")
    rows: list[list[T]] = []
    if r > n:
        return _SeqRows(move(rows), 0)
    indices: list[int] = []
    for j in range(r):
        indices.append(j)
    first: list[T] = []
    for j in range(r):
        first.append(iterable[indices[j]])
    rows.append(move(first))
    running: bool = True
    while running:
        found: int = -1
        i2: int = 0
        while i2 < r:
            i: int = r - 1 - i2
            if indices[i] != i + n - r:
                found = i
                break
            i2 += 1
        if found == -1:
            running = False
        else:
            bumped: int = indices[found] + 1
            indices[found] = bumped
            for j2 in range(found + 1, r):
                prev: int = indices[j2 - 1] + 1
                indices[j2] = prev
            row: list[T] = []
            for j3 in range(r):
                row.append(iterable[indices[j3]])
            rows.append(move(row))
    return _SeqRows(move(rows), 0)


def combinations_with_replacement(iterable: Ref[list[T]], r: int) -> _SeqRows[T]:
    """combinations_with_replacement(xs, r) — with repeated elements (as lists)."""
    n: int = len(iterable)
    if r < 0:
        raise ValueError("r must be non-negative")
    rows: list[list[T]] = []
    if n == 0 and r > 0:
        return _SeqRows(move(rows), 0)
    indices: list[int] = []
    for j in range(r):
        indices.append(0)
    first: list[T] = []
    for j in range(r):
        first.append(iterable[indices[j]])
    rows.append(move(first))
    if r == 0:
        return _SeqRows(move(rows), 0)
    running: bool = True
    while running:
        found: int = -1
        i2: int = 0
        while i2 < r:
            i: int = r - 1 - i2
            if indices[i] != n - 1:
                found = i
                break
            i2 += 1
        if found == -1:
            running = False
        else:
            new: int = indices[found] + 1
            for j2 in range(found, r):
                indices[j2] = new
            row: list[T] = []
            for j3 in range(r):
                row.append(iterable[indices[j3]])
            rows.append(move(row))
    return _SeqRows(move(rows), 0)
