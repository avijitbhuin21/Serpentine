"""Accept: Mut parameter — exclusive borrow; caller retains ownership afterwards."""

from serpentine import Mut, Owned


def append_tax(prices: Mut[list[float]]) -> None:
    for i in range(len(prices)):
        prices[i] *= 1.19


def main() -> None:
    prices: Owned[list[float]] = [10.0, 20.0]
    append_tax(prices)
    print(prices)


if __name__ == "__main__":
    main()
