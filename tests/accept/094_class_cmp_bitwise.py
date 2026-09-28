"""D39: class comparison dunders may return a class (mask objects); &, |, ^ and ~
desugar to __and__/__or__/__xor__/__invert__ on class operands; attribute access
and assignment from a __getitem__/comparison result."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass


@dataclass
class Mask:
    bits: list[bool]

    def __and__(self: Ref[Mask], other: Ref[Mask]) -> Mask:
        return Mask([self.bits[i] and other.bits[i] for i in range(len(self.bits))])

    def __or__(self: Ref[Mask], other: Ref[Mask]) -> Mask:
        return Mask([self.bits[i] or other.bits[i] for i in range(len(self.bits))])

    def __xor__(self: Ref[Mask], other: Ref[Mask]) -> Mask:
        return Mask([self.bits[i] != other.bits[i] for i in range(len(self.bits))])

    def __invert__(self: Ref[Mask]) -> Mask:
        return Mask([not b for b in self.bits])

    def count(self: Ref[Mask]) -> int:
        n: int = 0
        for b in self.bits:
            if b:
                n += 1
        return n


@dataclass
class Col:
    xs: list[int]

    def __gt__(self: Ref[Col], k: int) -> Mask:
        return Mask([x > k for x in self.xs])

    def __lt__(self: Ref[Col], k: int) -> Mask:
        return Mask([x < k for x in self.xs])

    def __ge__(self: Ref[Col], k: int) -> Mask:
        return Mask([x >= k for x in self.xs])

    def __le__(self: Ref[Col], k: int) -> Mask:
        return Mask([x <= k for x in self.xs])

    def __getitem__(self: Ref[Col], m: Ref[Mask]) -> Col:
        return Col([self.xs[i] for i in range(len(self.xs)) if m.bits[i]])


@dataclass
class Score:
    v: int

    def __lt__(self: Ref[Score], o: Ref[Score]) -> bool:
        return self.v < o.v


def main() -> None:
    c: Col = Col([1, 2, 3, 4, 5])
    m: Mask = c > 2
    print(m.bits)
    print((c > 1).bits, (c < 5).count(), (c >= 5).bits, (c <= 1).bits)
    both: Mask = (c > 1) & (c < 5)
    print(both.bits)
    print(((c > 4) | (c < 2)).bits)
    print(((c > 2) ^ (c > 3)).bits)
    print((~m).bits, (~(c > 3)).count())
    print(c[(c > 1) & ~(c > 4)].xs)
    print(c[c > 3].xs)
    print(Score(1) < Score(2), Score(3) < Score(2))
    if Score(1) < Score(2):
        print("bool compare still narrows")


if __name__ == "__main__":
    main()
