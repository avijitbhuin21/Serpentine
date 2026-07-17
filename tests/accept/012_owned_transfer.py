"""Accept: Owned parameter — explicit move() for named values, none for temporaries."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> int:
    return len(xs)


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    print(consume(move(xs)))
    print(consume([4, 5]))


if __name__ == "__main__":
    main()
