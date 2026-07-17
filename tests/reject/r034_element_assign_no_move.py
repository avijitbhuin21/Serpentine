# serp-reject: SE002 missing-move
"""Reject: element assignment moves the RHS in — named non-Copy values need move() (5.2)."""


def main() -> None:
    rows: list[list[int]] = [[1], [2]]
    fresh: list[int] = [9]
    rows[0] = fresh  # E: SE002
    print(rows)


if __name__ == "__main__":
    main()
