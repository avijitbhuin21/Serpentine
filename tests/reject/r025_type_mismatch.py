# serp-reject: SE214 type-mismatch
"""Reject: operand type mismatch — int + str has no Tier-0 meaning."""


def main() -> None:
    n: int = 1
    s: str = "x"
    print(n + s)  # E: SE214


if __name__ == "__main__":
    main()
