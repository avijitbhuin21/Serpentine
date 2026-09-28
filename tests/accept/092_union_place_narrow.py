"""Reading fields of a narrowed union member: every slot, not just the first.

Regression: llvmgen's `_place` hardcoded the Optional payload index, so a union
narrowed to any member after the first read the wrong slot (zeros, or a type
mismatch when the slots differed in shape).
"""
from __future__ import annotations

from serpentine import Owned, dataclass, move


@dataclass
class Cat:
    name: str
    meows: int


@dataclass
class Dog:
    name: str
    barks: float


@dataclass
class Bird:
    name: str
    tweets: str


def show(p: Owned[Cat | Dog | Bird]) -> str:
    """Render whichever member the union holds."""
    if isinstance(p, Cat):
        return "cat " + p.name + " " + str(p.meows)
    if isinstance(p, Dog):
        return "dog " + p.name + " " + str(p.barks)
    if isinstance(p, Bird):
        return "bird " + p.name + " " + p.tweets
    return "?"


def main() -> None:
    a: Cat | Dog | Bird = Cat("tom", 3)
    b: Cat | Dog | Bird = Dog("rex", 2.5)
    c: Cat | Dog | Bird = Bird("pip", "chirp")
    print(show(move(a)))
    print(show(move(b)))
    print(show(move(c)))


if __name__ == "__main__":
    main()
