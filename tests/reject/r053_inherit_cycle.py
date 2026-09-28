# serp-reject: SE201 unsupported-feature
"""Reject: inheritance cycles are impossible to flatten."""
from __future__ import annotations
from serpentine import dataclass


@dataclass
class A(B):  # E: SE201
    x: int = 0


@dataclass
class B(A):
    y: int = 0


def main() -> None:
    a: A = A()
    print(a.x)


if __name__ == "__main__":
    main()
