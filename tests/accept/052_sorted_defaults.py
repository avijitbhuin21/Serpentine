"""Tier-2 sorted() (keyless and key=lambda) and default parameter values."""
from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Board:
    tag: str

    def fmt(self: Ref[Board], sep: str = "-", reps: int = 2) -> str:
        out: str = self.tag
        for _i in range(reps - 1):
            out = out + sep + self.tag
        return out


def pad(text: str, width: int = 8, fill: str = ".") -> str:
    out: str = text
    while len(out) < width:
        out = out + fill
    return out


def main() -> None:
    nums: list[int] = [3, 1, 4, 1, 5, 9, 2, 6]
    print(sorted(nums))
    print(nums)
    words: list[str] = ["pear", "fig", "banana", "kiwi"]
    print(sorted(words))
    print(sorted(words, key=lambda w: len(w)))
    print(sorted(nums, key=lambda n: -n))
    floats: list[float] = [2.5, -1.0, 0.25]
    print(sorted(floats))
    print(pad("ab"), pad("ab", 4), pad("ab", 5, "*"))
    b: Board = Board("x")
    print(b.fmt(), b.fmt("+"), b.fmt("+", 3))


if __name__ == "__main__":
    main()
