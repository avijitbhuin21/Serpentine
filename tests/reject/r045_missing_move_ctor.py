# serp-reject: SE002 missing-move
"""Reject: passing a live non-Copy value to a constructor field without move()."""
from __future__ import annotations
from serpentine import dataclass


@dataclass
class Bag:
    items: list[int]
    tag: str


def main() -> None:
    xs: list[int] = [1, 2]
    bag: Bag = Bag(xs, "t")  # E: SE002
    print(bag.tag)


if __name__ == "__main__":
    main()
