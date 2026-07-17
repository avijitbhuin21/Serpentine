# serp-reject: SE001 use-after-move
"""Reject: E1 join — a value moved inside a try body is maybe-moved in except."""
from serpentine import Owned, move


def risky() -> int:
    raise ValueError("sometimes")


def sink(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: list[int] = [1, 2]
    try:
        sink(move(xs))
        print(risky())
    except ValueError:
        print(len(xs))  # E: SE001
    print("end")


if __name__ == "__main__":
    main()
