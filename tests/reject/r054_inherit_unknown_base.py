# serp-reject: SE201 unsupported-feature
"""Reject: a class base must name another @dataclass class visible in the module."""
from __future__ import annotations
from serpentine import dataclass


@dataclass
class Sub(Missing):  # E: SE201
    x: int = 0


def main() -> None:
    s: Sub = Sub()
    print(s.x)


if __name__ == "__main__":
    main()
