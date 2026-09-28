from __future__ import annotations

from serpentine import Callable


def announce(f: Callable[[int], int]) -> Callable[[int], int]:
    print("registered handler")
    return f


def tagged(tag: str) -> Callable[[Callable[[int], int]], Callable[[int], int]]:
    print("tag:", tag)
    return lambda f: f


@announce
@tagged("double")
def double(n: int) -> int:
    return n * 2


@announce
def triple(n: int) -> int:
    return n * 3


def main() -> None:
    print(double(7))
    print(triple(7))


if __name__ == "__main__":
    main()
