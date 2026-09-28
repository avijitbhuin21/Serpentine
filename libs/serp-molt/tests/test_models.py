"""serp-molt: model construction, dumping, validation and nested models."""
from __future__ import annotations

from typing import Annotated

from serp_molt import BaseModel, Field


class User(BaseModel):
    id: int
    name: str = Field(default="anon", min_length=2, max_length=10)
    age: Annotated[int, Field(ge=0, le=150)] = 0
    tags: list[str] = Field(default_factory=list)


class Address(BaseModel):
    city: str
    zipcode: str = Field(pattern="^[0-9]+$")


class Company(BaseModel):
    name: str
    hq: Address
    staff: list[User] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=dict)
    website: str | None = None


def main() -> None:
    u = User(id=1)
    print(u.id, u.name, u.age, len(u.tags))
    print(u.model_dump())
    print(u.model_dump_json())
    print(u)

    v = User.model_validate({"id": "7", "name": "ada", "age": 36.0,
                             "tags": ["a", "b"]})
    print(v.id, v.name, v.age, v.tags[1])
    print(v.model_dump_json())

    w = User.model_validate_json('{"id": 9, "name": "bo", "age": "12"}')
    print(w.model_dump())

    c = Company.model_validate({
        "name": "acme",
        "hq": {"city": "Pune", "zipcode": "411001"},
        "staff": [{"id": 1, "name": "ada"}, {"id": 2, "name": "bob", "age": 40}],
        "scores": {"q1": 10, "q2": "20"},
    })
    print(c.name, c.hq.city, c.hq.zipcode, len(c.staff))
    print(c.staff[1].name, c.staff[1].age, c.scores["q2"], c.website is None)
    print(c.model_dump())
    print(c.model_dump_json())

    d = c.model_dump(False, True)
    print(d)

    copy = v.model_copy({"name": "eve"})
    print(copy.model_dump())

    built = User.model_construct({"id": 3, "name": "cy"})
    print(built.model_dump())

    print(v.dict())
    print(v.json())

    empty = User(id=0, name="zz", age=1, tags=["t"])
    print(empty.model_dump_json())


if __name__ == "__main__":
    main()
