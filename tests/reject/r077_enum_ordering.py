# serp-reject: SE214 type-mismatch
"""Reject: enum values compare only with ==/!= against the same enum."""

from enum import Enum


class Color(Enum):
    RED = 1
    BLUE = 3


def main() -> None:
    a = Color.RED
    b = Color.BLUE
    print(a < b)  # E: SE214


if __name__ == "__main__":
    main()
