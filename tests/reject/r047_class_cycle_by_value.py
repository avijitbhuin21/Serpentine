# serp-reject: SE214 type-mismatch
"""Reject: a class containing itself by value has infinite size (rustc E0072)."""
from __future__ import annotations
from serpentine import dataclass


@dataclass
class Node:  # E: SE214
    val: int
    next: Node | None


def main() -> None:
    n: Node = Node(1, None)
    print(n.val)


if __name__ == "__main__":
    main()
