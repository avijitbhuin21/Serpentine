"""Generic dataclasses with methods, monomorphized per instantiation."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass, Generic, TypeVar

T = TypeVar("T")


@dataclass
class Box(Generic[T]):
    value: T

    def get_twice(self: Ref[Box]) -> str:
        return f"{self.value}{self.value}"


@dataclass
class Counter(Generic[T]):
    label: T
    count: int

    def bump(self: Mut[Counter]) -> None:
        self.count += 1


def main() -> None:
    bi: Box[int] = Box(21)
    bs: Box[str] = Box("ha")
    print(bi.value + 1)
    print(bi.get_twice())
    print(bs.get_twice())
    c: Counter[str] = Counter("hits", 0)
    c.bump()
    c.bump()
    print(c)


if __name__ == "__main__":
    main()
