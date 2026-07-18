# serp-reject: SE215 unsatisfied-protocol
"""Reject: class missing a protocol-required method fails the bound."""
from __future__ import annotations
from serpentine import Protocol, Ref, TypeVar, dataclass


class Named(Protocol):
    def label(self: Ref[Named]) -> str: ...


T = TypeVar("T", bound=Named)


@dataclass
class Point:
    x: int

    def norm(self: Ref[Point]) -> int:
        return self.x


def show(v: Ref[T]) -> None:
    print(v.label())


def main() -> None:
    p: Point = Point(3)
    show(p)  # E: SE215


if __name__ == "__main__":
    main()
