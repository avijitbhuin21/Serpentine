# serp-reject: SE214 type-mismatch
"""Reject: extraction from PyVal is explicit — no implicit PyVal -> int assignment."""
from serpentine import PyVal


def main() -> None:
    v: PyVal = 3
    n: int = v  # E: SE214
    print(n)


if __name__ == "__main__":
    main()
