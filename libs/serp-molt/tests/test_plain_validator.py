from __future__ import annotations

from serp_molt import BaseModel
from serpentine import PyVal, field_validator


class Item(BaseModel):
    code: str

    @field_validator("code", mode="plain")
    @classmethod
    def norm(cls, v: PyVal) -> PyVal:
        """A plain validator replaces validation for `code` entirely."""
        return str(v).upper()


def main() -> None:
    m: Item = Item.model_validate({"code": "abc"})
    print(m.code)
    print(m.model_dump_json())
    n: Item = Item.model_validate({"code": "xyz"})
    print(n.code)


if __name__ == "__main__":
    main()
