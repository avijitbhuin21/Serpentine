# serp-reject: SE001 use-after-move
"""Reject: maybe-moved at a join — moved on one branch, used after the if (J8)."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    if len(xs) > 2:
        consume(move(xs))
    print(len(xs))  # E: SE001


if __name__ == "__main__":
    main()
