"""Tier-2 structural protocols as generic bounds."""
from __future__ import annotations
from serpentine import Protocol, Ref, Mut, TypeVar, dataclass


class Named(Protocol):
    def label(self: Ref[Named]) -> str: ...


class Sizable(Protocol):
    def grow(self: Mut[Sizable], by: int) -> int: ...


T = TypeVar("T", bound=Named)
U = TypeVar("U", bound=Sizable)


@dataclass
class Dog:
    name: str
    size: int

    def label(self: Ref[Dog]) -> str:
        return f"dog:{self.name}"

    def grow(self: Mut[Dog], by: int) -> int:
        self.size += by
        return self.size


@dataclass
class Cat:
    lives: int

    def label(self: Ref[Cat]) -> str:
        return f"cat:{self.lives}"


def show(x: Ref[T]) -> None:
    print(x.label())


def bump(x: Mut[U]) -> int:
    return x.grow(3)


def main() -> None:
    d: Dog = Dog("rex", 10)
    c: Cat = Cat(9)
    show(d)
    show(c)
    print(bump(d))
    print(bump(d))
    show(d)


if __name__ == "__main__":
    main()
