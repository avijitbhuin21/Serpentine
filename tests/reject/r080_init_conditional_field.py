# serp-reject: SE201 unsupported-feature
"""Reject: a field assigned inside a branch of __init__ (not definitely assigned)."""
from __future__ import annotations
from serpentine import Mut, dataclass


@dataclass
class Score:
    value: int
    tag: str

    def __init__(self: Mut[Score], value: int) -> None:
        self.value = value
        if value > 10:
            self.tag = "high"  # E: SE201
        else:
            self.tag = "low"


def main() -> None:
    s: Score = Score(4)
    print(s.tag)


if __name__ == "__main__":
    main()
