# serp-reject: SE218 ambiguous-union
"""Two union members with the same runtime kind cannot be told apart by isinstance()."""
from __future__ import annotations


def pick(v: list[int] | list[str]) -> int:   # E: SE218
    if isinstance(v, list):
        return len(v)
    return 0


def main() -> None:
    print(pick([1, 2]))


if __name__ == "__main__":
    main()
