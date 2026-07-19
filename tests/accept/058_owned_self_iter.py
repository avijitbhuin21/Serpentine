"""Owned (consuming) self methods and first-class iterators."""
from __future__ import annotations
from serpentine import Owned, Ref, dataclass, move


@dataclass
class Batch:
    items: list[int]

    def size(self: Ref[Batch]) -> int:
        return len(self.items)

    def into_sum(self: Owned[Batch]) -> int:
        return sum(self.items)


def main() -> None:
    b: Batch = Batch([1, 2, 3])
    print(b.size())
    print(move(b).into_sum())
    print(Batch([10, 20]).into_sum())
    xs: list[int] = [7, 8, 9]
    if len(xs) > 0:
        it = iter(xs)
        print(next(it), next(it))
        rest: int = 0
        try:
            while True:
                rest += next(it)
        except StopIteration:
            print("drained", rest)
    xs.append(10)
    words: list[str] = ["a", "b"]
    w = iter(words)
    print(next(w), next(w))
    try:
        print(next(w))
    except StopIteration:
        print("exhausted")
    print(xs)


if __name__ == "__main__":
    main()
