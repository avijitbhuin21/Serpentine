"""Benchmark: float arithmetic — Leibniz series for pi, 10M terms."""


def leibniz(terms: int) -> float:
    acc: float = 0.0
    sign: float = 1.0
    k: float = 1.0
    i: int = 0
    while i < terms:
        acc += sign / k
        sign = -sign
        k += 2.0
        i += 1
    return acc * 4.0


def main() -> None:
    print(leibniz(10000000))


if __name__ == "__main__":
    main()
