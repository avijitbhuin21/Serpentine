"""Subclass an imported base: inherited fields, methods, override, AssertionError."""
from __future__ import annotations
from counterlib import Counter
from serpentine import Ref, dataclass


@dataclass
class Clicker(Counter):
    clicks: int = 0

    def label(self: Ref[Clicker]) -> str:
        return "clicker"


def main() -> None:
    c: Clicker = Clicker()
    c.bump()
    c.bump(2)
    print(c.count)
    print(c.label())
    c.check_positive()
    d: Clicker = Clicker()
    try:
        d.check_positive()
    except AssertionError as e:
        print(f"caught: {e}")


if __name__ == "__main__":
    main()
