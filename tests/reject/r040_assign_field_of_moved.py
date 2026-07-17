# serp-reject: SE001 use-after-move
"""Reject: assigning to a field of a wholly moved value (rustc E0382 parity)."""
from __future__ import annotations
from serpentine import Owned, dataclass, move


@dataclass
class Bag:
    items: list[int]
    tag: str


def sink(b: Owned[Bag]) -> None:
    print(b.tag)


def main() -> None:
    bag: Bag = Bag([1], "t")
    sink(move(bag))
    bag.tag = "new"  # E: SE001
    print(bag.tag)


if __name__ == "__main__":
    main()
