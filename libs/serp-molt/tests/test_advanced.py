"""serp-molt: enum, set and union field types (LB5/LB6/LB7)."""
from __future__ import annotations

from enum import Enum

from serp_molt import BaseModel, ValidationError


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class Level(Enum):
    LOW = 1
    HIGH = 2


class Tagged(BaseModel):
    name: str
    color: Color
    level: Level
    tags: set[str]
    ident: int | str
    note: str | None = None


def main() -> None:
    t = Tagged.model_validate({"name": "a", "color": "red", "level": 2,
                               "tags": ["x", "x"], "ident": 7})
    print(t.name, t.color.value, t.color.name, t.level.value, len(t.tags))
    if isinstance(t.ident, int):
        print("int ident", t.ident)
    print(t.model_dump_json())

    u = Tagged.model_validate({"name": "b", "color": "blue", "level": 1,
                               "tags": ["only"], "ident": "sku-1"})
    print(u.model_dump())
    if isinstance(u.ident, str):
        print("str ident", u.ident)

    try:
        bad = Tagged.model_validate({"name": "c", "color": "green", "level": 1,
                                     "tags": [], "ident": 1})
        print("unreachable", bad.name)
    except ValidationError as e:
        print(e)

    for er in Tagged.model_validate_errors({"name": "d", "color": "red", "level": 9,
                                            "tags": "nope", "ident": 1.5}):
        print(er["type"], er["loc"], er["msg"])

    print(Tagged.model_json_schema())


if __name__ == "__main__":
    main()
