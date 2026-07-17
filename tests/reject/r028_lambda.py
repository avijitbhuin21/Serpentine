# serp-reject: SE201 unsupported-feature
"""Reject: lambda expressions are Tier 2 (closures)."""


def main() -> None:
    f = lambda x: x * 2  # E: SE201
    print(f(21))


if __name__ == "__main__":
    main()
