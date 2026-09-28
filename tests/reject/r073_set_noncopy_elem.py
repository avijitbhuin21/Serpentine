# serp-reject: SE201 unsupported-feature
"""Reject: set elements must be Copy types (LB7)."""


def main() -> None:
    grid: set[list[int]] = set()  # E: SE201
    print(len(grid))


if __name__ == "__main__":
    main()
