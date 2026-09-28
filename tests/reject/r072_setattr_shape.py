# serp-reject: SE201 unsupported-feature
"""Reject: __setattr__ must take (self: Mut[C], name: str, value: PyVal) -> None."""

from __future__ import annotations

from serpentine import Mut, dataclass


@dataclass
class Box:
    value: int

    def __setattr__(self: Mut[Box], name: str) -> None:  # E: SE201
        print(name)


def main() -> None:
    b = Box(value=1)
    print(b.value)


if __name__ == "__main__":
    main()
