# serp-reject: SE201 unsupported-feature
"""Reject: a non-defaulted dataclass field cannot follow a defaulted one."""
from __future__ import annotations
from serpentine import dataclass


@dataclass
class Bad:
    a: int = 1
    b: str  # E: SE201


def main() -> None:
    x: Bad = Bad(1, "s")
    print(x.b)


if __name__ == "__main__":
    main()
