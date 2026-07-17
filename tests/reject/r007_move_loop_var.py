# serp-reject: SE007 move-loop-variable
"""Reject: the non-Copy loop variable is a per-iteration Ref and cannot be moved (5.4)."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    rows: list[list[int]] = [[1], [2]]
    for row in rows:
        consume(move(row))  # E: SE007


if __name__ == "__main__":
    main()
