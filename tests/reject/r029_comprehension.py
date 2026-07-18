# serp-reject: SE201 unsupported-feature
"""Reject: Tier-2 comprehensions take exactly one 'for' clause."""


def main() -> None:
    xss: list[list[int]] = [[1, 2], [3]]
    flat: list[int] = [x for xs in xss for x in xs]  # E: SE201
    print(flat)


if __name__ == "__main__":
    main()
