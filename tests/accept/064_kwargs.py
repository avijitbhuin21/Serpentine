"""Accept: keyword arguments on user functions and methods (Tier 2)."""

from __future__ import annotations
from serpentine import Ref, dataclass


def scaled(n: int, factor: int = 2, offset: int = 0) -> int:
    return n * factor + offset


def label(text: str, prefix: str = "[", suffix: str = "]") -> str:
    return prefix + text + suffix


@dataclass
class Box:
    value: int

    def bump(self: Ref[Box], amount: int = 1, times: int = 1) -> int:
        return self.value + amount * times


def main() -> None:
    print(scaled(10))
    print(scaled(10, factor=3))
    print(scaled(10, offset=5))
    print(scaled(10, offset=5, factor=4))
    print(scaled(n=7))
    print(label("hi"))
    print(label("hi", suffix=">"))
    print(label(text="hi", prefix="<", suffix=">"))
    b = Box(100)
    print(b.bump())
    print(b.bump(times=3))
    print(b.bump(amount=5, times=2))


if __name__ == "__main__":
    main()
