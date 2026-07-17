# serp-reject: SE002 missing-move
"""Reject: append takes its argument as Owned — named non-Copy values need move() (7.1)."""


def main() -> None:
    rows: list[list[int]] = []
    row: list[int] = [1, 2]
    rows.append(row)  # E: SE002
    print(rows)


if __name__ == "__main__":
    main()
