# serp-reject: SE001 use-after-move
"""Reject: using the whole value after one of its fields was moved out."""
from __future__ import annotations
from serpentine import dataclass, move


@dataclass
class Bag:
    items: list[int]
    tag: str


def main() -> None:
    bag: Bag = Bag([1, 2], "t")
    items: list[int] = move(bag.items)
    print(bag)  # E: SE001
    print(len(items))


if __name__ == "__main__":
    main()
