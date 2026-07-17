# serp-reject: SE201 unsupported-feature
"""Reject: the walrus operator is not in the Tier-0 grammar (3.2)."""


def main() -> None:
    xs: list[int] = [1, 2, 3]
    if (n := len(xs)) > 2:  # E: SE201
        print(n)


if __name__ == "__main__":
    main()
