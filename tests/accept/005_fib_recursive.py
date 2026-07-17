"""Accept: recursive functions over Copy types."""


def fib(n: int) -> int:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def main() -> None:
    print(fib(20))


if __name__ == "__main__":
    main()
