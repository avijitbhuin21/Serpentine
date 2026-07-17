"""Accept: list literals, append, insert, Copy-element indexing, container repr."""


def main() -> None:
    xs: list[int] = [1, 2, 3]
    xs.append(4)
    xs.insert(0, 0)
    print(len(xs))
    print(xs[0], xs[4])
    print(xs)


if __name__ == "__main__":
    main()
