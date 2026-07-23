# serp-reject: SE214 type-mismatch
"""Reject: unknown keyword argument name at a user-function call site."""


def scaled(n: int, factor: int = 2) -> int:
    return n * factor


def main() -> None:
    print(scaled(3, scale=4))  # E: SE214


if __name__ == "__main__":
    main()
