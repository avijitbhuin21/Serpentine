"""Accept: float arithmetic and shortest-roundtrip repr surface (divergence D7)."""


def main() -> None:
    x: float = 0.1
    y: float = 0.2
    print(x + y)
    print(3.5 // 2.0, 3.5 % 2.0)
    print(abs(-2.5))
    print(float(3))


if __name__ == "__main__":
    main()
