# serp-reject: SE008 move-out-of-borrow
"""Reject: moving a field out of a borrowed (Ref/Mut) parameter leaves a hole."""
from __future__ import annotations
from serpentine import Mut, dataclass, move


@dataclass
class Bag:
    items: list[int]
    tag: str


def steal(bag: Mut[Bag]) -> None:
    items: list[int] = move(bag.items)  # E: SE008
    print(len(items))


def main() -> None:
    b: Bag = Bag([1], "t")
    steal(b)


if __name__ == "__main__":
    main()
