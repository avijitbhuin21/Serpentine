"""Accept: tuples of Copy elements are Copy — free duplication and indexing."""


def main() -> None:
    p: tuple[int, int] = (3, 4)
    q: tuple[int, int] = p
    print(p[0] + q[1])
    r: tuple[str, float] = ("pi", 3.14)
    print(r[0], r[1])


if __name__ == "__main__":
    main()
