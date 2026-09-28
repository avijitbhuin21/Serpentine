"""serp-molt: Json markers, root models and PydanticCustomError."""
from __future__ import annotations

from serp_molt import (BaseModel, Field, Json, PydanticCustomError, SkipValidation,
                       ValidationError, field_validator)
from serpentine import PyVal
from typing import Annotated


class Payload(BaseModel):
    name: str = ""
    tags: Annotated[list[str], Json()] = []
    counts: Annotated[dict[str, int], Json()] = {}


class Ids(BaseModel):
    root: list[int] = []


class Code(BaseModel):
    value: str = ""

    @field_validator("value", mode="after")
    @classmethod
    def check(cls, v: PyVal) -> PyVal:
        if str(v) != "bar":
            raise PydanticCustomError(f"not_a_bar: value is not 'bar', got {v}")
        return v


class Loose(BaseModel):
    n: Annotated[int, Field(gt=100), SkipValidation()] = 0


def main() -> None:
    p = Payload.model_validate({"name": "p", "tags": "[\"a\",\"b\"]",
                                "counts": "{\"x\":1}"})
    print(p.name, p.tags, p.counts)
    print(p.model_dump_json())
    print(Payload.model_fields_set({"name": "p", "tags": "[]"}))
    try:
        Payload.model_validate({"tags": "[oops"})
    except ValidationError as e:
        print(str(e))
    ids = Ids.model_validate([1, 2, 3])
    print(ids.root, ids.model_dump(), ids.model_dump_json())
    try:
        Ids.model_validate([1, "x"])
    except ValidationError as e2:
        print(str(e2))
    okc = Code.model_validate({"value": "bar"})
    print(okc.value)
    try:
        Code.model_validate({"value": "baz"})
    except ValidationError as e3:
        print(str(e3))
    lo = Loose.model_validate({"n": 5})
    print(lo.n, lo.model_dump_json())


if __name__ == "__main__":
    main()
