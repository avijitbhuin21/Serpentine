# serp-reject: SE201 unsupported-feature
"""Reject: Tier-2 default parameter values must be literal constants."""


def scaled(n: int = 2 * 21) -> int:  # E: SE201
    return n


def main() -> None:
    print(scaled())


if __name__ == "__main__":
    main()
