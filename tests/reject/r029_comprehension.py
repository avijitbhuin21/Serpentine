# serp-reject: SE201 unsupported-feature
"""Reject: dict comprehensions take exactly one 'for' clause (list/set ones may take several)."""


def main() -> None:
    xss: list[list[int]] = [[1, 2], [3]]
    flat: dict[int, int] = {x: x for xs in xss for x in xs}  # E: SE201
    print(flat)


if __name__ == "__main__":
    main()
