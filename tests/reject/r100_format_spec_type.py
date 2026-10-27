# serp-reject: SE214 type-mismatch
"""Reject: a format spec on a list (CPython raises TypeError: unsupported format string)."""


def main() -> None:
    xs: list[int] = [1, 2]
    print(f"[{xs:>10}]")  # E: SE214


if __name__ == "__main__":
    main()
