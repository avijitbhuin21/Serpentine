"""Accept: reduction builtins over Ref-borrowed lists, plus scalar forms."""


def main() -> None:
    xs: list[int] = [5, 3, 9, 1]
    print(sum(xs), min(xs), max(xs))
    print(min(2, 7), max(2, 7))
    print(abs(-9), abs(2.5))


if __name__ == "__main__":
    main()
