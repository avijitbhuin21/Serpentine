"""Function references in build-time metadata: Annotated markers and ConfigDict."""
from __future__ import annotations

from typing import Annotated

from serpentine import (ConfigDict, PyVal, dataclass, fields_json, hooks_json,
                        run_hook)


def shout(v: PyVal) -> PyVal:
    """Upper-case a string value."""
    return str(v).upper()


def to_camel(v: PyVal) -> PyVal:
    """Turn a snake_case name into camelCase."""
    parts: list[str] = str(v).split("_")
    out: str = parts[0]
    idx: int = 1
    while idx < len(parts):
        p: str = parts[idx]
        if len(p) > 0:
            out = out + p[0].upper() + p[1:]
        idx += 1
    return out


@dataclass
class Check:
    """Marker recording a validator function in field metadata."""

    func: PyVal


@dataclass
class Item:
    name: Annotated[str, Check(shout)] = "x"
    kind: str = "k"

    model_config = ConfigDict(alias_generator=to_camel)


def main() -> None:
    fj: str = fields_json(Item)
    print('"annotated":[{"call":"Check","args":[{"__fn__":"shout"}]}]' in fj)
    print('"alias_generator":{"__fn__":"to_camel"}' in fj)

    hj: str = hooks_json(Item)
    print('"funcs":["shout","to_camel"]' in hj)

    print(run_hook(Item, "shout", "abc"))
    print(run_hook(Item, "to_camel", "user_name"))
    print(run_hook(Item, "nope", "kept"))


if __name__ == "__main__":
    main()
