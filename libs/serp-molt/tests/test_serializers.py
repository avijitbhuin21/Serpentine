"""serp-molt: field/model serializers, computed fields and ValidationInfo."""
from __future__ import annotations

from serp_molt import (BaseModel, ValidationError, computed_field, field_serializer,
                       field_validator, model_serializer)
from serpentine import PyVal, Ref


class Product(BaseModel):
    name: str
    price: float
    qty: int

    @field_serializer("price")
    def ser_price(self: Ref[Product], v: PyVal) -> PyVal:
        return f"${v}"

    @computed_field
    @property
    def total(self: Ref[Product]) -> float:
        return self.price * float(self.qty)

    @computed_field
    def slug(self: Ref[Product]) -> str:
        return self.name.lower().replace(" ", "-")

    @field_validator("qty")
    @classmethod
    def check_qty(cls, v: PyVal, info: PyVal) -> PyVal:
        if int(v) <= 0:
            raise ValueError(f"{info['field_name']} must be positive")
        return v


class Pair(BaseModel):
    left: int
    right: int

    @model_serializer
    def as_list(self: Ref[Pair]) -> PyVal:
        out: list[PyVal] = [self.left, self.right]
        return out


def main() -> None:
    p = Product.model_validate({"name": "Wax Candle", "price": 2.5, "qty": 4})
    print(p.model_dump())
    print(p.model_dump_json())

    try:
        bad = Product.model_validate({"name": "x", "price": 1.0, "qty": 0})
        print("unreachable", bad.name)
    except ValidationError as e:
        print(e)

    q = Pair.model_validate({"left": 1, "right": 2})
    print(q.model_dump())
    print(q.model_dump_json())

    print(Product.model_json_schema())
    print(Product.model_json_schema("serialization"))


if __name__ == "__main__":
    main()
