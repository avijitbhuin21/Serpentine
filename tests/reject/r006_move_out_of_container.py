# serp-reject: SE006 move-out-of-container
"""Reject: moving a non-Copy element out by index would leave a hole (5.1)."""

from serpentine import Owned, move


def main() -> None:
    rows: list[list[int]] = [[1], [2]]
    first: Owned[list[int]] = move(rows[0])  # E: SE006
    print(first)


if __name__ == "__main__":
    main()
