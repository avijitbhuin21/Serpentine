# serp-reject: SE201 unsupported-feature
"""Reject: multiple inheritance is not supported (single base only)."""
from __future__ import annotations
from serpentine import dataclass


@dataclass
class A:
    x: int = 0


@dataclass
class B:
    y: int = 0


@dataclass
class C(A, B):  # E: SE201
    z: int = 0


def main() -> None:
    c: C = C()
    print(c.z)


if __name__ == "__main__":
    main()
