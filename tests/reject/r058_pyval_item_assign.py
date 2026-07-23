# serp-reject: SE214 type-mismatch
"""Reject: PyVal values are immutable — item assignment is not supported."""
from serpentine import PyVal


def main() -> None:
    v: PyVal = [1, 2, 3]
    v[0] = 9  # E: SE214
    print(v)


if __name__ == "__main__":
    main()
