# serp-reject: SE202 invalid-wrapper-position
"""Reject: ownership wrappers nested inside a container element type (2.1)."""

from serpentine import Ref


def main() -> None:
    xs: list[Ref[int]] = []  # E: SE202
    print(len(xs))


if __name__ == "__main__":
    main()
