# serp-reject: SE213 foreign-import
"""Reject: relative imports are not supported — dotted paths from the project root only."""

from .util import helper  # E: SE213


def main() -> None:
    print(helper())


if __name__ == "__main__":
    main()
