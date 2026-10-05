"""Traceback probe: a caught error must not leak frames; the uncaught one reports every .py frame."""
from serpentine import Ref


def level3(xs: Ref[list[int]], i: int) -> int:
    """Index out of range three frames down."""
    return xs[i]


def level2(n: int) -> int:
    """Calls level3 with a possibly bad index."""
    data: list[int] = [1, 2, 3]
    return level3(data, n)


def swallow() -> int:
    """Catch an error so its frames must be discarded."""
    try:
        return level2(99)
    except IndexError:
        return -1


def main() -> None:
    print("start")
    print(swallow())
    print(level2(1))
    print(level2(10))
    print("unreachable")


if __name__ == "__main__":
    main()
