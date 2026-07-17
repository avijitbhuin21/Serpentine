"""Accept: rebinding via explicit move; the new owner is fully usable."""

from serpentine import Owned, move


def main() -> None:
    xs: Owned[list[int]] = [1, 2, 3]
    ys: Owned[list[int]] = move(xs)
    ys.append(4)
    print(ys)


if __name__ == "__main__":
    main()
