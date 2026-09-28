# serp-reject: SE214 type-mismatch
"""isinstance() must name one of the union's own members."""
from __future__ import annotations


def check(v: int | str) -> bool:
    return isinstance(v, float)   # E: SE214


def main() -> None:
    print(check(3))


if __name__ == "__main__":
    main()
