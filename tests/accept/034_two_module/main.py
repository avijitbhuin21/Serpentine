"""Accept: multi-module program — bin-1 import of a sibling Serpentine module."""

from mathutil import mean


def main() -> None:
    xs: list[float] = [1.0, 2.0, 3.0, 4.0]
    print(mean(xs))


if __name__ == "__main__":
    main()
