# serp-reject: SE201 unsupported-feature
"""Reject: a metadata-referenced function must be (v: PyVal) -> PyVal."""

from __future__ import annotations

from typing import Annotated

from serpentine import PyVal, dataclass, hooks_json


def bump(v: int) -> int:
    """Add one."""
    return v + 1


@dataclass
class Check:
    """Marker recording a validator function in field metadata."""

    func: PyVal


@dataclass
class Item:
    name: Annotated[str, Check(bump)] = "x"


def main() -> None:
    print(hooks_json(Item))  # E: SE201


if __name__ == "__main__":
    main()
