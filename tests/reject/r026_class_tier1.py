# serp-reject: SE201 unsupported-feature
"""Reject: class definitions are Tier 1, not Tier 0 (1.2)."""


class Point:  # E: SE201
    pass


def main() -> None:
    print("never checked past the class")


if __name__ == "__main__":
    main()
