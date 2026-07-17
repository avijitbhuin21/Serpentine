"""Accept: non-Copy loop variable is a per-iteration Ref, used read-only (SPEC 5.4)."""


def main() -> None:
    rows: list[list[int]] = [[1], [2, 3], [4, 5, 6]]
    count: int = 0
    for row in rows:
        count += len(row)
    print(count)


if __name__ == "__main__":
    main()
