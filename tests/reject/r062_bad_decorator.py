# serp-reject: SE214 type-mismatch
"""Reject: a decorator must produce a Callable matching the decorated signature."""

from serpentine import Callable


def deco(f: Callable[[int], int]) -> Callable[[str], str]:
    return lambda s: s


@deco
def double(n: int) -> int:  # E: SE214
    return n * 2


def main() -> None:
    print(double(2))


if __name__ == "__main__":
    main()
