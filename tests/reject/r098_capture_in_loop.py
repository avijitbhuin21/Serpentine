# serp-reject: SE005 move-while-borrowed
"""Reject: capturing a non-Copy value in a lambda built inside a loop (a later iteration
could change the original before the copy-holding closure runs)."""
from serpentine import Callable


def main() -> None:
    names: list[str] = ["a"]
    fs: list[Callable[[], int]] = []
    for i in range(2):
        fs.append(lambda: len(names))  # E: SE005
        names.append("b")
    print(fs[0]())


if __name__ == "__main__":
    main()
