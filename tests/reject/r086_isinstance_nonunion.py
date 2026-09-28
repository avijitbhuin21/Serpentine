# serp-reject: SE201 unsupported-feature
"""isinstance() is a union tag test only: it cannot probe a plain non-union value."""
from __future__ import annotations


def check(v: int) -> bool:
    return isinstance(v, int)   # E: SE201


def main() -> None:
    print(check(3))


if __name__ == "__main__":
    main()
