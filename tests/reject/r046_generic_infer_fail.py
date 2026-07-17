# serp-reject: SE204 unknown-element-type
"""Reject: a generic call whose type variable cannot be inferred from arguments."""
from serpentine import TypeVar, Ref

T = TypeVar("T")


def emptiness(xs: Ref[list[T]]) -> int:
    return len(xs)


def main() -> None:
    print(emptiness([]))  # E: SE204


if __name__ == "__main__":
    main()
