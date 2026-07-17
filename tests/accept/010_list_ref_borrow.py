"""Accept: Ref parameter — immutable borrow for the duration of the call."""

from serpentine import Ref


def total(prices: Ref[list[float]]) -> float:
    return sum(prices)


def main() -> None:
    prices: list[float] = [9.99, 4.5, 1.25]
    print(total(prices))
    print(len(prices))


if __name__ == "__main__":
    main()
