# serp-reject: SE214 type-mismatch
"""Reject: the integer presentation type 'd' on a float (CPython raises ValueError)."""


def main() -> None:
    price: float = 9.5
    print(f"{price:05d}")  # E: SE214


if __name__ == "__main__":
    main()
