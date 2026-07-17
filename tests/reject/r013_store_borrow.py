# serp-reject: SE202 invalid-wrapper-position
"""Reject: Ref/Mut on a local would be a stored borrow — parameters only (2.1, J5)."""

from serpentine import Ref


def main() -> None:
    xs: list[int] = [1, 2, 3]
    r: Ref[list[int]] = xs  # E: SE202
    print(len(r))


if __name__ == "__main__":
    main()
