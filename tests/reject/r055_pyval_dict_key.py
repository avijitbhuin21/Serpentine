# serp-reject: SE201 unsupported-feature
"""Reject: PyVal is not hashable-ordered — it cannot be used as a dict key."""
from serpentine import PyVal


def main() -> None:
    d: dict[PyVal, int] = {}  # E: SE201
    print(len(d))


if __name__ == "__main__":
    main()
