"""Accept: integer arithmetic incl. floor division/modulo on negatives (divergence D4)."""


def main() -> None:
    a: int = -7
    b: int = 2
    print(a + b, a - b, a * b)
    print(a // b, a % b)
    print(7 // 2, 7 % 2, -7 % -2)
    print(2 ** 10)
    print(a / b)


if __name__ == "__main__":
    main()
