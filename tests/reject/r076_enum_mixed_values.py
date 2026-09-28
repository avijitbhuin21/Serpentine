# serp-reject: SE201 unsupported-feature
"""Reject: an enum cannot mix int and str member values."""

from enum import Enum


class Mixed(Enum):  # E: SE201
    A = 1
    B = "two"


def main() -> None:
    print(Mixed.A.name)


if __name__ == "__main__":
    main()
