"""Accept: Copy types never move — duplication of int and str; move() is a no-op copy."""

from serpentine import move


def main() -> None:
    a: int = 41
    b: int = a
    a += 1
    print(a, b)
    s: str = "snake"
    t: str = s
    print(s, t)
    c: int = move(a)
    print(a, c)


if __name__ == "__main__":
    main()
