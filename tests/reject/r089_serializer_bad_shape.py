# serp-reject: SE201 unsupported-feature
"""Reject: @field_serializer must be (self: Ref[C], v: PyVal) -> PyVal."""
from __future__ import annotations
from serpentine import PyVal, Ref, dataclass, field_serializer, hooks_json


@dataclass
class Item:
    name: str

    @field_serializer("name")
    def ser_name(self: Ref[Item]) -> PyVal:
        return self.name


def main() -> None:
    print(hooks_json(Item))  # E: SE201


if __name__ == "__main__":
    main()
