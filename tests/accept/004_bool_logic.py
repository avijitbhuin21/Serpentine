"""Accept: bool logic, chained comparisons, explicit int(b) conversion (divergence D5)."""


def main() -> None:
    t: bool = True
    f: bool = 1 > 2
    print(t and not f)
    print(t or f)
    print(1 < 2 < 3)
    print(int(t) + int(f))


if __name__ == "__main__":
    main()
