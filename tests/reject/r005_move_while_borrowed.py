# serp-reject: SE005 move-while-borrowed
"""Reject: moving the iterable while the for loop's Ref borrow is live (J1, 5.4)."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    for x in xs:
        if x == 2:
            consume(move(xs))  # E: SE005


if __name__ == "__main__":
    main()
