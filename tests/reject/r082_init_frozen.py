# serp-reject: SE201 unsupported-feature
"""Reject: __init__ on a frozen dataclass — a frozen instance has no field writes."""
from __future__ import annotations
from serpentine import Mut, dataclass


@dataclass(frozen=True)
class Key:
    raw: str

    def __init__(self: Mut[Key], raw: str) -> None:  # E: SE201
        self.raw = raw.strip()


def main() -> None:
    k: Key = Key(" a ")
    print(k.raw)


if __name__ == "__main__":
    main()
