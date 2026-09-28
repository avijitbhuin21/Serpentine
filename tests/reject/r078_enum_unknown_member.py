# serp-reject: SE214 type-mismatch
"""Reject: unknown enum member access is a static error."""

from enum import Enum


class Color(Enum):
    RED = 1
    BLUE = 3


def main() -> None:
    print(Color.GREEN.value)  # E: SE214


if __name__ == "__main__":
    main()
