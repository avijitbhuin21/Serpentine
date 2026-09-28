"""Serializer, computed-field and two-argument validator hooks (D27)."""

from __future__ import annotations

from serpentine import (PyVal, Ref, computed_field, dataclass, field_serializer,
                        field_validator, hooks_json, model_serializer, run_hook_get,
                        run_hook_info, run_hook_val)


@dataclass
class Box:
    w: int
    h: int
    label: str = "box"

    @field_serializer("w", "h")
    def ser_side(self: Ref[Box], v: PyVal) -> PyVal:
        return f"{v}cm"

    @computed_field
    @property
    def area(self: Ref[Box]) -> int:
        return self.w * self.h

    @computed_field
    def shout(self: Ref[Box]) -> str:
        return self.label.upper()

    @field_validator("w")
    @classmethod
    def check_w(cls, v: PyVal, info: PyVal) -> PyVal:
        if int(v) < 0:
            raise ValueError("width may not be negative")
        return v


@dataclass
class Point:
    x: int
    y: int

    @model_serializer
    def to_pair(self: Ref[Point]) -> PyVal:
        out: list[PyVal] = [self.x, self.y]
        return out


def main() -> None:
    print(hooks_json(Box))
    print(hooks_json(Point))
    b = Box(w=3, h=4, label="crate")
    print(run_hook_val(b, "ser_side", b.w))
    print(run_hook_val(b, "ser_side", b.h))
    print(run_hook_get(b, "area"), run_hook_get(b, "shout"))
    print(b.area)
    info: dict[str, PyVal] = {"field_name": "w", "data": {}}
    print(run_hook_info(Box, "check_w", 5, info))
    try:
        print(run_hook_info(Box, "check_w", -1, info))
    except ValueError as e:
        print("rejected:", e)
    p = Point(x=1, y=2)
    print(run_hook_get(p, "to_pair"))
    print(run_hook_get(p, "missing"))


if __name__ == "__main__":
    main()
