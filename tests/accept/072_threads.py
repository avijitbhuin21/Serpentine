from __future__ import annotations

from serpentine import spawn


def sum_to(n: int, tag: str) -> str:
    total: int = 0
    for i in range(n):
        total += i
    return tag + "=" + str(total)


def scale(x: float, k: float) -> float:
    return x * k


def is_even(n: int) -> bool:
    return n % 2 == 0

def boom(n: int) -> int:
    if n > 0:
        raise ValueError("bad input")
    return n


def main() -> None:
    h1 = spawn(sum_to, 100, "a")
    h2 = spawn(sum_to, 50, "b")
    h3 = spawn(scale, 2.5, 4.0)
    h4 = spawn(is_even, 7)
    print(h1.join())
    print(h2.join())
    print(h3.join())
    print(h4.join())
    hb = spawn(boom, 5)
    try:
        x: int = hb.join()
        print(x)
    except ValueError as e:
        print("caught:", e)


if __name__ == "__main__":
    main()
