"""Generic functions: monomorphized per call-site argument types."""
from serpentine import Ref, Owned, TypeVar, move

T = TypeVar("T")


def last(xs: Ref[list[T]]) -> int:
    return len(xs)


def swallow(x: Owned[T]) -> None:
    print("gone")


def main() -> None:
    ints: list[int] = [1, 2, 3]
    words: list[str] = ["a", "b"]
    print(last(ints))
    print(last(words))
    swallow(move(ints))
    n: int = 5
    swallow(n)
    print(len(words))


if __name__ == "__main__":
    main()
