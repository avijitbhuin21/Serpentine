# serp-reject: SE202 invalid-wrapper-position
"""Reject: Owned self — consuming methods are Tier 2; self must be Ref or Mut."""
from __future__ import annotations
from serpentine import Owned, dataclass


@dataclass
class Token:
    value: str

    def consume(self: Owned[Token]) -> str:  # E: SE202
        return self.value


def main() -> None:
    t: Token = Token("x")
    print(t.value)


if __name__ == "__main__":
    main()
