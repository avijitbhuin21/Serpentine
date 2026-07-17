"""Accept: overwriting a container element drops the old value (SPEC 5.1, 5.2)."""

from serpentine import move


def main() -> None:
    rows: list[list[int]] = [[1], [2]]
    rows[0] = [7, 8]
    fresh: list[int] = [9]
    rows[1] = move(fresh)
    print(rows)


if __name__ == "__main__":
    main()
