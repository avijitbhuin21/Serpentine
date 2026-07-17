"""Exceptions crossing function boundaries: raise in callee, catch in caller."""


def risky(n: int) -> int:
    if n < 0:
        raise ValueError("negative input")
    return n * 2


def middle(n: int) -> int:
    return risky(n) + 1


def main() -> None:
    print(middle(5))
    try:
        print(middle(-3))
    except ValueError as e:
        print("caught:", e)
    try:
        print(risky(-1))
    except ZeroDivisionError as e:
        print("wrong handler:", e)
    except ValueError as e:
        print("right handler:", e)
    print("end")


if __name__ == "__main__":
    main()
