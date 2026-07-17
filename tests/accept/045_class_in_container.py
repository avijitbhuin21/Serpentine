"""Class instances inside containers: list of dataclasses, iteration by Ref."""
from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Item:
    name: str
    qty: int

    def line(self: Ref[Item]) -> str:
        return f"{self.name} x{self.qty}"


def main() -> None:
    items: list[Item] = []
    items.append(Item("apple", 3))
    items.append(Item("pear", 5))
    total: int = 0
    for it in items:
        print(it.line())
        total += it.qty
    print(total)
    print(items[0].name)
    print(len(items))
    print(items[1])


if __name__ == "__main__":
    main()
