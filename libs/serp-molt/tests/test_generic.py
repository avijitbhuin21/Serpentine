"""serp-molt: generic models (LB9)."""
from __future__ import annotations

from typing import Generic, TypeVar

from serp_molt import BaseModel, ValidationError

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    total: int
    items: list[T]


def main() -> None:
    p = Page[int].model_validate({"total": 2, "items": [1, 2]})
    print(p.total, p.items)
    print(p.model_dump_json())
    print(Page[int].model_json_schema())

    q = Page[str].model_validate({"total": 1, "items": ["a"]})
    print(q.items, q.model_dump())

    try:
        bad = Page[int].model_validate({"total": 1, "items": ["x"]})
        print("unreachable", bad.total)
    except ValidationError as e:
        print(e)

    for er in Page[str].model_validate_errors({"total": "n", "items": [1]}):
        print(er["type"], er["loc"])


if __name__ == "__main__":
    main()
