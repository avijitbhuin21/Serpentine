"""Accept: union-typed fields through the field-table intrinsics (LB5)."""

from __future__ import annotations

from serpentine import PyVal, Ref, dataclass, fields_build, fields_json, fields_of


@dataclass
class Item:
    tag: str
    val: int | str
    extra: float | str | None
    tags: list[int | str]


def show(i: Ref[Item]) -> None:
    """Print every field of an item."""
    d = fields_of(i)
    for k, v in d.items():
        print(k, "=", v)


def main() -> None:
    """Dump, describe and rebuild a model whose fields are unions."""
    a = Item(tag="a", val=1, extra=None, tags=[1, "x"])
    show(a)
    b = Item(tag="b", val="two", extra=2.5, tags=[])
    show(b)
    print(fields_json(Item))
    data: dict[str, PyVal] = {"tag": "c", "val": "three", "extra": "e", "tags": [9]}
    c = fields_build(Item, data)
    show(c)
    data2: dict[str, PyVal] = {"tag": "d", "val": 4, "extra": 1.5, "tags": ["z", 3]}
    show(fields_build(Item, data2))


if __name__ == "__main__":
    main()
