"""Accept: in-place Mut receiver methods — key-less sort, reverse, clear."""


def main() -> None:
    xs: list[int] = [3, 1, 2]
    xs.sort()
    print(xs)
    xs.reverse()
    print(xs)
    xs.clear()
    print(len(xs))


if __name__ == "__main__":
    main()
