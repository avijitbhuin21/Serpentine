# serp-reject: SE001 use-after-move
"""Reject: double move — the second move() reads an already-moved-out place (J1)."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    consume(move(xs))
    consume(move(xs))  # E: SE001


if __name__ == "__main__":
    main()
