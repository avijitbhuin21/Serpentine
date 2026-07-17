"""Accept: iterative fib with while loop; 64-bit-representable result."""


def fib(n: int) -> int:
    a: int = 0
    b: int = 1
    i: int = 0
    while i < n:
        t: int = a + b
        a = b
        b = t
        i += 1
    return a


def main() -> None:
    print(fib(50))


if __name__ == "__main__":
    main()
