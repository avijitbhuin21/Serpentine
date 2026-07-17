"""Accept: a moved-out variable becomes usable again after reassignment (J1)."""

from serpentine import Owned, move


def consume(xs: Owned[list[int]]) -> None:
    print(len(xs))


def main() -> None:
    xs: Owned[list[int]] = [1, 2]
    consume(move(xs))
    xs = [3, 4, 5]
    print(len(xs))


if __name__ == "__main__":
    main()
