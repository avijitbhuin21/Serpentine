# serp-reject: SE214 type-mismatch
"""Reject: @field_serializer naming a field the class does not declare."""
from __future__ import annotations
from serpentine import PyVal, Ref, dataclass, field_serializer, hooks_json


@dataclass
class Item:
    name: str

    @field_serializer("nope")
    def ser_nope(self: Ref[Item], v: PyVal) -> PyVal:
        return v


def main() -> None:
    print(hooks_json(Item))  # E: SE214


if __name__ == "__main__":
    main()
