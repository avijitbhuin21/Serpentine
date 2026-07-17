"""Field-sensitive partial moves: move x.f while x.g stays live, re-init, whole use."""
from __future__ import annotations
from serpentine import Owned, dataclass, move


@dataclass
class Bag:
    items: list[int]
    tag: str


def consume(xs: Owned[list[int]]) -> int:
    return len(xs)


def main() -> None:
    bag: Bag = Bag([1, 2, 3], "first")
    items: list[int] = move(bag.items)
    print(bag.tag)
    print(consume(move(items)))
    bag.items = [7, 8]
    print(bag)


if __name__ == "__main__":
    main()
