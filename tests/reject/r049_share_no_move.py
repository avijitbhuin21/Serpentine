# serp-reject: SE002 missing-move
"""Reject: share() takes ownership — a live non-Copy value needs move()."""
from serpentine import Shared, share


def main() -> None:
    xs: list[int] = [1, 2]
    s: Shared[list[int]] = share(xs)  # E: SE002
    print(len(s))


if __name__ == "__main__":
    main()
