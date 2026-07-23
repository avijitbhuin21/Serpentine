# serp-reject: SE005 move-while-borrowed
"""Reject: capturing a loop-assigned variable (CPython late-binding divergence)."""
from serpentine import Callable


def main() -> None:
    fs: list[Callable[[int], int]] = []
    for i in range(3):
        fs.append(lambda x: x + i)  # E: SE005
    print(fs[0](1))


if __name__ == "__main__":
    main()
