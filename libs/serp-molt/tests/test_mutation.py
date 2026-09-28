"""serp-molt: keyword unpacking, frozen/validate_assignment, Annotated validators."""
from __future__ import annotations

from serp_molt import (AfterValidator, BeforeValidator, BaseModel, ConfigDict, Field,
                       ValidationError)
from serpentine import PyVal
from typing import Annotated


def shout(v: PyVal) -> PyVal:
    """Uppercase a validated string."""
    return str(v).upper()


def strip_dash(v: PyVal) -> PyVal:
    """Drop dashes from a raw input string."""
    return str(v).replace("-", "")


def to_camel(v: PyVal) -> PyVal:
    """`first_name` -> `firstName`."""
    parts: list[str] = str(v).split("_")
    out: str = parts[0]
    i: int = 1
    while i < len(parts):
        out = out + parts[i][0:1].upper() + parts[i][1:]
        i = i + 1
    return out


class Tag(BaseModel):
    name: Annotated[str, AfterValidator(shout)] = "x"
    code: Annotated[str, BeforeValidator(strip_dash)] = ""


class Live(BaseModel):
    name: str = Field(min_length=2)
    hits: int = 0

    model_config = ConfigDict(validate_assignment=True)


class Stone(BaseModel):
    name: str = ""

    model_config = ConfigDict(frozen=True)


class Person(BaseModel):
    first_name: str = ""
    last_name: str = ""

    model_config = ConfigDict(alias_generator=to_camel)


def main() -> None:
    payload: dict[str, PyVal] = {"name": "ada", "hits": 3}
    a: Live = Live(**payload)
    print(a.name, a.hits)

    b: Live = Live(**{"name": "bob", "hits": 1})
    print(b.name, b.hits)

    t: Tag = Tag.model_validate({"name": "ada", "code": "1-2-3"})
    print(t.name, t.code)

    c: Live = Live.model_validate({"name": "eve"})
    c.hits = 7
    print(c.name, c.hits)
    try:
        c.name = "z"
    except ValidationError as e1:
        print("assign-rejected")
        print(str(e1))

    s: Stone = Stone.model_validate({"name": "rock"})
    try:
        s.name = "sand"
    except ValidationError as e2:
        print("frozen-rejected")
        print(str(e2))
    print(s.name)

    p: Person = Person.model_validate({"firstName": "ada", "lastName": "lovelace"})
    print(p.first_name, p.last_name)
    print(p.model_dump_json(True))


if __name__ == "__main__":
    main()
