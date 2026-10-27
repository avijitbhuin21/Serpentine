from __future__ import annotations
from serp_bigint import BigInt, big, bigdivmod
from serpentine import move


def factorial(n: int) -> BigInt:
    """n! as a BigInt."""
    acc: BigInt = big(1)
    for i in range(2, n + 1):
        acc = acc * big(i)
    return acc


def main() -> None:
    f30: BigInt = factorial(30)
    print(f30, f30.fits_int())
    f100: BigInt = factorial(100)
    print(len(str(f100)), str(f100)[0:20], str(f100)[len(str(f100)) - 30:len(str(f100))])
    two: BigInt = big(2)
    p: BigInt = two ** 200
    print(p)
    m: BigInt = big(9223372036854775807) + big(1)
    print(m, m.fits_int(), (m - big(1)).to_int())
    a: BigInt = BigInt.parse("-123456789012345678901234567890")
    b: BigInt = BigInt.parse("987654321")
    print(a // b, a % b, -a // b, a // -b)
    qr: list[BigInt] = bigdivmod(a, b)
    print(qr[0], qr[1])
    print(a < b, a == BigInt.parse("-123_456_789_012_345_678_901_234_567_890"), abs(a) > b)
    print(f"{p!r}", big(0), -big(0), big(-5) ** 3)
    fib_a: BigInt = big(0)
    fib_b: BigInt = big(1)
    for i in range(300):
        nxt: BigInt = fib_a + fib_b
        fib_a = move(fib_b)
        fib_b = move(nxt)
    print("fib300:", fib_a)
    try:
        print(big(1) // big(0))
    except ZeroDivisionError as e:
        print("caught:", e)
    try:
        print(p.to_int())
    except OverflowError as e2:
        print("caught:", e2)
    try:
        print(BigInt.parse("12x3"))
    except ValueError as e3:
        print("caught:", e3)


if __name__ == "__main__":
    main()
