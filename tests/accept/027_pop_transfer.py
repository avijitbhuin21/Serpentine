"""Accept: pop removes and transfers ownership of a non-Copy element (SPEC 5.1)."""


def main() -> None:
    rows: list[list[int]] = [[1, 2], [3, 4, 5]]
    last: list[int] = rows.pop()
    print(len(last), len(rows))
    first: list[int] = rows.pop(0)
    print(first)


if __name__ == "__main__":
    main()
