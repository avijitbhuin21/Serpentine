# serp-reject: SE214 type-mismatch
"""Reject: PyVal supports only ==/!= — ordering comparisons need extraction first."""
from serpentine import PyVal


def main() -> None:
    v: PyVal = 3
    print(v < 5)  # E: SE214


if __name__ == "__main__":
    main()
