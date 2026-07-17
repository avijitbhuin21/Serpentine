# serp-reject: SE209 returned-borrow
"""Reject: Ref in return position — return values are always owned in Tier 0 (J5, D2)."""

from serpentine import Ref


def head(xs: Ref[list[int]]) -> Ref[list[int]]:  # E: SE209
    return xs


def main() -> None:
    xs: list[int] = [1, 2]
    print(head(xs))


if __name__ == "__main__":
    main()
