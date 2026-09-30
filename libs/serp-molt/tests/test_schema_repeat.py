from __future__ import annotations

from serp_molt import BaseModel, Field
from serpentine import PyVal


class Tiny(BaseModel):
    id: int


class Aliased(BaseModel):
    user_id: int = Field(alias="userId")
    name: str


def main() -> None:
    """Regenerate schemas many times: guards the Backend-B str-ternary temp-drop crash in _model_json."""
    total: int = 0
    j: int = 0
    while j < 300:
        s: PyVal = Tiny.model_json_schema()
        total += len(s)
        if j % 100 == 0:
            print("schema", j, len(s))
        j += 1
    print("total", total)
    print(Aliased.model_json_schema())
    print(Aliased.model_json_schema(by_alias=False))


if __name__ == "__main__":
    main()
