# serp-reject: SE201 unsupported-feature
"""Reject: enum bodies hold constant members only — no methods."""

from enum import Enum


class Color(Enum):  # E: SE201
    RED = 1

    def describe(self) -> str:
        return "red"


def main() -> None:
    print(Color.RED.value)


if __name__ == "__main__":
    main()
