# serp-reject: SE201 unsupported-feature
"""Reject: comprehensions are not in the Tier-0 grammar (3.2)."""


def main() -> None:
    xs: list[int] = [x * x for x in range(5)]  # E: SE201
    print(xs)


if __name__ == "__main__":
    main()
