# serp-reject: SE004 conflicting-borrow
"""Reject: a lambda mutating its captured non-Copy value (each call would mutate a private
copy, while CPython mutates the shared object)."""
from serpentine import Callable


def main() -> None:
    log: list[str] = []
    record: Callable[[str], None] = lambda msg: log.append(msg)  # E: SE004
    record("a")
    print(len(log))


if __name__ == "__main__":
    main()
