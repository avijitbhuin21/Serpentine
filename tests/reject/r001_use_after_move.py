# serp-reject: SE001 use-after-move
"""Reject: reading a variable after move() transferred its ownership (J1, J2)."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    consume(move(xs))
    print(len(xs))  # E: SE001


if __name__ == "__main__":
    main()
