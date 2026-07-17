"""Accept: value moved on every branch, then reassigned before any use (J8)."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    flag: bool = len(xs) > 2
    if flag:
        consume(move(xs))
    else:
        consume(move(xs))
    xs = [9]
    print(xs[0])


if __name__ == "__main__":
    main()
