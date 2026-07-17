# serp-reject: SE001 use-after-move
"""Reject: use-after-move applies to dicts exactly as to lists (J1, J2)."""

from serpentine import Owned, move


def consume(d: Owned[dict[str, int]]) -> None:
    print(len(d))


def main() -> None:
    d: Owned[dict[str, int]] = {"a": 1}
    consume(move(d))
    print(d["a"])  # E: SE001


if __name__ == "__main__":
    main()
