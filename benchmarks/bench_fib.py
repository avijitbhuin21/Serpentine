"""Benchmark: recursive fib(32) — function-call + int arithmetic throughput."""


def fib(n: int) -> int:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def main() -> None:
    print(fib(32))


if __name__ == "__main__":
    main()
