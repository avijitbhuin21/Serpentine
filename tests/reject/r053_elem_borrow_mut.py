# serp-reject: SE004 conflicting-borrow
"""Reject: mutating a container while a named element borrow is live."""


def main() -> None:
    rows: list[list[int]] = [[1, 2], [3]]
    first = rows[0]
    rows.append([4])  # E: SE004
    print(first)


if __name__ == "__main__":
    main()
