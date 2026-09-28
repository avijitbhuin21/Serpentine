"""serp-molt: ValidationError text, error lists, aliases and JSON Schema."""
from __future__ import annotations

from typing import Annotated

from serp_molt import BaseModel, Field, ValidationError


class Item(BaseModel):
    sku: str = Field(alias="SKU", min_length=3)
    qty: Annotated[int, Field(gt=0, le=99)] = 1
    price: float = Field(0.0, ge=0.0)
    note: str | None = None


class Cart(BaseModel):
    owner: str = Field(min_length=2, description="who owns the cart")
    items: list[Item] = Field(default_factory=list)


def main() -> None:
    ok = Item.model_validate({"SKU": "abc", "qty": 5, "price": "1.5"})
    print(ok.sku, ok.qty, ok.price, ok.note is None)
    print(ok.model_dump(True))
    print(ok.model_dump_json(True, True))

    try:
        bad = Item.model_validate({"SKU": "ab", "qty": 0, "price": -1.0})
        print("unreachable", bad.sku)
    except ValidationError as e:
        print(e)

    try:
        missing = Item.model_validate({"qty": 2})
        print("unreachable", missing.sku)
    except ValidationError as e:
        print(e)

    try:
        wrong = Item.model_validate({"SKU": "abc", "qty": "many"})
        print("unreachable", wrong.qty)
    except ValidationError as e:
        print(e)

    errs = Item.model_validate_errors({"SKU": "x", "qty": 200})
    print(len(errs))
    for er in errs:
        print(er["type"], er["loc"], er["msg"], er["input"])

    cart = Cart.model_validate({"owner": "ada",
                                "items": [{"SKU": "aaa", "qty": 2, "price": 3.0}]})
    print(cart.owner, len(cart.items), cart.items[0].sku)
    print(cart.model_dump_json())

    nested = Cart.model_validate_errors({"owner": "a",
                                         "items": [{"SKU": "aa", "qty": 0}]})
    for er in nested:
        print(er["type"], er["loc"])

    print(Item.model_json_schema())
    print(Cart.model_json_schema())
    print(Item.model_fields())


if __name__ == "__main__":
    main()
