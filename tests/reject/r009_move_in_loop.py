# serp-reject: SE001 use-after-move
"""Reject: move inside a loop body — moved-out at the loop head on iteration 2 (J8)."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    i: int = 0
    while i < 3:
        consume(move(xs))  # E: SE001
        i += 1


if __name__ == "__main__":
    main()
