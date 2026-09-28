# serp-reject: SE201 unsupported-feature
"""Inheriting from a generic class is not supported: only the subclass may be generic."""
from __future__ import annotations
from typing import Generic, TypeVar
from serpentine import dataclass

T = TypeVar("T")


@dataclass
class Box(Generic[T]):
    item: T


@dataclass
class IntBox(Box[int]):   # E: SE201
    tag: str


def main() -> None:
    b: IntBox = IntBox(1, "x")
    print(b.item, b.tag)


if __name__ == "__main__":
    main()
