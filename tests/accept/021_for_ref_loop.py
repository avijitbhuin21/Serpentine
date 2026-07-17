"""Accept: for takes a Ref of the list; Copy loop variable is freely usable."""


def main() -> None:
    xs: list[int] = [1, 2, 3, 4]
    total: int = 0
    for x in xs:
        total += x
    print(total)
    print(len(xs))


if __name__ == "__main__":
    main()
