# serp-reject: SE214 type-mismatch
"""Reject: build-time metadata referencing a name that is not a function."""

from __future__ import annotations

from typing import Annotated

from serpentine import PyVal, dataclass, hooks_json


@dataclass
class Check:
    """Marker recording a validator function in field metadata."""

    func: PyVal


@dataclass
class Item:
    name: Annotated[str, Check(nope)] = "x"


def main() -> None:
    print(hooks_json(Item))  # E: SE214


if __name__ == "__main__":
    main()
