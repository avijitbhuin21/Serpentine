"""try/except/finally: catchable runtime errors, raise, handler binding."""


def main() -> None:
    xs: list[int] = [1, 2, 3]
    try:
        print(xs[10])
    except IndexError as e:
        print("caught:", e)
    finally:
        print("finally")

    try:
        n: int = 7 // 0
        print(n)
    except ZeroDivisionError as e:
        print(e)

    try:
        raise ValueError("boom")
    except ValueError as e:
        print("value:", e)

    d: dict[str, int] = {"a": 1}
    try:
        print(d["missing"])
    except KeyError as e:
        print("key:", e)

    try:
        print(int("nope"))
    except Exception as e:
        print("any:", e)

    print(len(xs))


if __name__ == "__main__":
    main()
