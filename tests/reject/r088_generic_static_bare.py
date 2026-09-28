# serp-reject: SE214 type-mismatch
"""A classmethod of a generic class needs an explicit instantiation at the call site."""
from __future__ import annotations
from typing import Generic, Self, TypeVar

from serpentine import PyVal, dataclass, fields_build

T = TypeVar("T")


@dataclass
class Box(Generic[T]):
    label: str
    items: list[T]

    @classmethod
    def of(cls, data: PyVal) -> Self:
        """Build a box from a plain mapping."""
        return fields_build(cls, data)


def main() -> None:
    src: dict[str, PyVal] = {"label": "nums", "items": [1]}
    b = Box.of(src)   # E: SE214
    print(b.label)


if __name__ == "__main__":
    main()
