"""Repr parity: float shortest-roundtrip, exponents, containers, quote rules."""


def main() -> None:
    print(0.1 + 0.2)
    print(1.0 / 3.0)
    print(10000000000000000.0)
    print(0.000015)
    print(-0.0)
    print(2.5e-10)
    print(float("inf"))
    print(float("-inf"))
    print(float("nan"))
    print(9007199254740993.0)
    xs: list[float] = [1.0, 0.5, 2.0e20]
    print(xs)
    d: dict[str, float] = {"a": 1.5, "b": -0.25}
    print(d)
    t: tuple[int, float, str] = (1, 2.0, "x")
    print(t)
    quotes: list[str] = ["it's", 'say "hi"', "both'\"here", "tab\there"]
    print(quotes)
    print(3.14)
    print(1e100)
    print(5e-324)


if __name__ == "__main__":
    main()
