# serp-reject: SE002 missing-move
"""Reject: consuming methods (Owned self) need an explicit move() receiver."""
from __future__ import annotations
from serpentine import Owned, dataclass


@dataclass
class Token:
    value: str

    def consume(self: Owned[Token]) -> str:
        return self.value


def main() -> None:
    t: Token = Token("x")
    print(t.consume())  # E: SE002


if __name__ == "__main__":
    main()
