# serp-reject: SE004 conflicting-borrow
"""Reject: self-aliasing call — Mut receiver and Ref argument on the same place (J4)."""


def main() -> None:
    xs: list[int] = [1, 2, 3]
    xs.extend(xs)  # E: SE004
    print(xs)


if __name__ == "__main__":
    main()
