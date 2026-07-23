"""User iterator protocol: __iter__/__next__, for-loops, next(), StopIteration."""
from __future__ import annotations
from serpentine import Callable, Generic, Mut, Ref, TypeVar, dataclass, move

T = TypeVar("T")


@dataclass
class Filt(Generic[T]):
    xs: list[T]
    i: int
    pred: Callable[[T], bool]

    def __iter__(self: Ref[Filt[T]]) -> Filt[T]:
        return self

    def __next__(self: Mut[Filt[T]]) -> T:
        while self.i < len(self.xs):
            v: T = self.xs[self.i]
            self.i += 1
            if self.pred(v):
                return v
        raise StopIteration()


@dataclass
class Pairs(Generic[T]):
    xs: list[T]
    i: int

    def __iter__(self: Ref[Pairs[T]]) -> Pairs[T]:
        return self

    def __next__(self: Mut[Pairs[T]]) -> tuple[T, T]:
        if self.i + 1 >= len(self.xs):
            raise StopIteration()
        a: T = self.xs[self.i]
        b: T = self.xs[self.i + 1]
        self.i += 1
        return (a, b)


def filt(xs: Ref[list[T]], pred: Callable[[T], bool]) -> Filt[T]:
    buf: list[T] = []
    for i in range(len(xs)):
        buf.append(xs[i])
    return Filt(move(buf), 0, pred)


def pairs(xs: Ref[list[T]]) -> Pairs[T]:
    buf: list[T] = []
    for i in range(len(xs)):
        buf.append(xs[i])
    return Pairs(move(buf), 0)


def main() -> None:
    nums: list[int] = [1, 2, 3, 4, 5, 6]
    f: Filt[int] = filt(nums, lambda x: x % 2 == 0)
    print(next(f))
    for v in f:
        print(v)
    words: list[str] = ["aa", "b", "ccc"]
    for w in filt(words, lambda s: len(s) > 1):
        print(w)
    tens: list[int] = [10, 20, 30, 40]
    for a, b in pairs(tens):
        print(a, b)
    total: int = 0
    for v2 in filt(nums, lambda x: x > 1):
        if v2 == 3:
            continue
        total += v2
        if v2 == 4:
            break
    print("total", total)
    g: Filt[int] = filt([7], lambda x: True)
    try:
        print(next(g))
        print(next(g))
    except StopIteration:
        print("exhausted")


if __name__ == "__main__":
    main()
