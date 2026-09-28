"""serp-molt: self-referential models through list fields."""
from __future__ import annotations

from serp_molt import BaseModel, Field, ValidationError
from serpentine import Ref


class Node(BaseModel):
    name: str
    kids: list[Node] = Field(default_factory=list)


class Chain(BaseModel):
    label: str = Field(alias="L")
    rest: list[Chain] = Field(default_factory=list)


def depth(n: Ref[Node]) -> int:
    """The height of a validated tree."""
    best: int = 0
    for kid in n.kids:
        d: int = depth(kid)
        if d > best:
            best = d
    return best + 1


def main() -> None:
    tree = Node.model_validate({"name": "root",
                               "kids": [{"name": "a"},
                                        {"name": "b",
                                         "kids": [{"name": "c", "kids": []}]}]})
    print(tree.name, len(tree.kids), tree.kids[1].kids[0].name)
    print(tree.model_dump_json())
    print(depth(tree))

    flat = Node.model_validate({"name": "leaf"})
    print(flat.model_dump_json(), len(flat.kids))

    errs = Node.model_validate_errors({"name": "r", "kids": [{"name": 1},
                                                            {"kids": []}]})
    for er in errs:
        print(er["type"], er["loc"], er["msg"])

    ch = Chain.model_validate({"L": "one", "rest": [{"L": "two"}]})
    print(ch.label, ch.rest[0].label)
    print(ch.model_dump_json(True))

    try:
        bad = Node.model_validate({"name": "r", "kids": "nope"})
        print("unreachable", bad.name)
    except ValidationError as e:
        print(e)

    print(Node.model_json_schema())


if __name__ == "__main__":
    main()
