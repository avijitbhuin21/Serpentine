# serp-reject: SE201 unsupported-feature
"""Reject: __next__ must take Mut[self] and return a non-None value."""
from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Bad:
    i: int

    def __next__(self: Ref[Bad]) -> int:  # E: SE201
        return self.i


def main() -> None:
    b: Bad = Bad(0)
    print(b.i)


if __name__ == "__main__":
    main()
