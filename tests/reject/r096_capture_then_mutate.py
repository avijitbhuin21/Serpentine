# serp-reject: SE004 conflicting-borrow
"""Reject: mutating a non-Copy value after a lambda captured it (the closure holds a copy,
CPython's closure would see the change)."""
from serpentine import Callable


def main() -> None:
    items: list[int] = [1, 2]
    count: Callable[[], int] = lambda: len(items)
    items.append(3)  # E: SE004
    print(count())


if __name__ == "__main__":
    main()
