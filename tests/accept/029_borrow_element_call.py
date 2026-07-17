"""Accept: borrowing a container element for the duration of a call (SPEC 5.1)."""

from serpentine import Ref


def first(xs: Ref[list[int]]) -> int:
    return xs[0]


def main() -> None:
    rows: list[list[int]] = [[10, 20], [30]]
    print(first(rows[0]))
    rows[1].append(40)
    print(rows)


if __name__ == "__main__":
    main()
