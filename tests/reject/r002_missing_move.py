# serp-reject: SE002 missing-move
"""Reject: passing a live owned value to an Owned parameter without move() (J3)."""

from serpentine import Owned


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    consume(xs)  # E: SE002


if __name__ == "__main__":
    main()
