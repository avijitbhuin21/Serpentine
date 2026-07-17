"""Accept: ternary expressions and chained comparisons."""


def clamp(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else hi if x > hi else x


def main() -> None:
    print(clamp(5, 0, 10), clamp(-5, 0, 10), clamp(15, 0, 10))
    x: int = 5
    print(0 <= x <= 10)


if __name__ == "__main__":
    main()
