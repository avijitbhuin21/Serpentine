"""Classmethods on a generic class, called through an explicit instantiation."""
from __future__ import annotations
from typing import Generic, Self, TypeVar

from serpentine import PyVal, Ref, dataclass, fields_build, fields_json

T = TypeVar("T")


@dataclass
class Box(Generic[T]):
    label: str
    items: list[T]

    @classmethod
    def of(cls, data: PyVal) -> Self:
        """Build a box from a plain mapping."""
        return fields_build(cls, data)

    @classmethod
    def describe(cls) -> str:
        """The field table of this instantiation."""
        return fields_json(cls)

    def size(self: Ref[Box[T]]) -> int:
        """How many items the box holds."""
        return len(self.items)

    def first(self: Ref[Box[T]]) -> T:
        """The first item."""
        return self.items[0]


def main() -> None:
    """Exercise generic classmethods over two instantiations."""
    src: dict[str, PyVal] = {"label": "nums", "items": [1, 2, 3]}
    b: Box[int] = Box[int].of(src)
    print(b.label, b.items, b.size(), b.first())
    print(Box[int].describe())

    ssrc: dict[str, PyVal] = {"label": "words", "items": ["a", "b"]}
    s: Box[str] = Box[str].of(ssrc)
    print(s.label, s.items, s.size(), s.first())
    print(Box[str].describe())

    try:
        bad = Box[int].of({"label": "x", "items": ["nope"]})
        print("unreachable", bad.label)
    except TypeError as e:
        print("rejected:", e)


if __name__ == "__main__":
    main()
