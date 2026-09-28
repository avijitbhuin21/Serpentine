# serp-reject: SE216 not-send
"""Reject: spawning a function whose parameter type cannot cross a thread (D9)."""

from serpentine import Owned, spawn


def work(xs: Owned[list[int]]) -> int:
    return len(xs)


def main() -> None:
    xs: list[int] = [1, 2, 3]
    h = spawn(work, xs)  # E: SE216
    print(h.join())


if __name__ == "__main__":
    main()
