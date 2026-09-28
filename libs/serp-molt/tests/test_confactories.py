"""serp-molt constrained-type factories: conint/confloat/constr/conbytes/conlist."""
from __future__ import annotations

from serp_molt import BaseModel, ValidationError, conint, conlist, constr
from serpentine import PyVal

Age = conint(gt=0, le=130)
Name = constr(min_length=2, max_length=8)
Tags = conlist(str, min_length=1)


class Person(BaseModel):
    name: Name
    age: Age
    tags: Tags


def main() -> None:
    p: Person = Person.model_validate({"name": "ada", "age": 36, "tags": ["x"]})
    print(p.name, p.age, p.tags)
    print(p.model_dump_json())

    errs: list[PyVal] = Person.model_validate_errors({"name": "a", "age": 200, "tags": []})
    for e in errs:
        print(e["type"], e["loc"], e["msg"])

    caught: bool = False
    try:
        bad: Person = Person.model_validate({"name": "bob", "age": 0, "tags": ["t"]})
    except ValidationError as exc:
        caught = True
        print(str(exc))
    print(caught)

    schema: PyVal = Person.model_json_schema()
    print(schema["properties"]["age"])
    print(schema["properties"]["name"])
    print(schema["properties"]["tags"])


if __name__ == "__main__":
    main()
