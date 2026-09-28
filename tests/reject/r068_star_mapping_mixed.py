# serp-reject: SE201 unsupported-feature
"""Reject: `**mapping` cannot be mixed with other constructor arguments."""

from __future__ import annotations

from serpentine import PyVal, dataclass


@dataclass
class Point:
    x: int
    y: int = 0


def main() -> None:
    d: dict[str, PyVal] = {"y": 2}
    p = Point(1, **d)  # E: SE201
    print(p.x, p.y)


if __name__ == "__main__":
    main()
