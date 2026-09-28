# serp-reject: SE210 unnarrowed-union
"""A union value must be narrowed with isinstance() before it is used as one member."""
from __future__ import annotations


def double(v: int | str) -> int:
    return v * 2   # E: SE210


def main() -> None:
    print(double(3))


if __name__ == "__main__":
    main()
