"""serp-molt: strict field types, json_schema_extra, exclude, by_alias schema, context."""
from __future__ import annotations

from serp_molt import (BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr,
                       ValidationError, model_validator)
from serpentine import PyVal, pyval_kind


class Cfg(BaseModel):
    count: StrictInt
    ratio: StrictFloat
    flag: StrictBool
    name: StrictStr


class Rec(BaseModel):
    secret: str = Field(exclude=True)
    tag: str = Field("t", json_schema_extra={"x-order": 2})
    first_name: str = Field("ada", alias="firstName")


class Mixed(BaseModel):
    v: int | str


class Ctx(BaseModel):
    n: int

    @model_validator(mode="before")
    @classmethod
    def scale(cls, data: PyVal, info: PyVal) -> PyVal:
        ctx: PyVal = info["context"]
        if pyval_kind(ctx) == "NoneType":
            return data
        out: dict[str, PyVal] = {"n": int(data["n"]) * int(ctx["factor"])}
        return out


def main() -> None:
    ok = Cfg.model_validate({"count": 3, "ratio": 1.5, "flag": True, "name": "ada"})
    print(ok.count, ok.ratio, ok.flag, ok.name)

    widened = Cfg.model_validate({"count": 3, "ratio": 2, "flag": False, "name": "x"})
    print(widened.ratio)

    for er in Cfg.model_validate_errors({"count": "3", "ratio": "1.5", "flag": 1,
                                         "name": 7}):
        print(er["type"], er["loc"], er["msg"])

    try:
        bad = Cfg.model_validate({"count": True, "ratio": 1.0, "flag": True, "name": "a"})
        print("unreachable", bad.count)
    except ValidationError as e:
        print(e)

    rec = Rec.model_validate({"secret": "s3cr3t", "firstName": "grace"})
    print(rec.secret, rec.first_name)
    print(rec.model_dump_json())
    print(rec.model_dump_json(True))
    print(Rec.model_json_schema())
    print(Rec.model_json_schema("validation", False))

    for er2 in Mixed.model_validate_errors({"v": [1, 2]}):
        print(er2["type"], er2["loc"], er2["msg"])

    plain = Ctx.model_validate({"n": 4})
    print(plain.n)
    scaled = Ctx.model_validate({"n": 4}, {"factor": 5})
    print(scaled.n)
    from_json = Ctx.model_validate_json('{"n": 2}', {"factor": 3})
    print(from_json.n)


if __name__ == "__main__":
    main()
