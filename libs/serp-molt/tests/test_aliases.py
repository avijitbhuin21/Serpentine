"""serp-molt: constrained and format type aliases."""
from __future__ import annotations

from serp_molt import (BaseModel, EmailStr, HttpUrl, NonNegativeInt, PositiveFloat,
                       PositiveInt, ValidationError)


class Account(BaseModel):
    id: PositiveInt
    credits: NonNegativeInt = 0
    rate: PositiveFloat = 1.5
    site: HttpUrl = "https://example.com"
    email: EmailStr = "a@b.co"


def main() -> None:
    a = Account(id=3, credits=0, rate=2.5, site="https://serpentine.dev/docs",
                email="me@site.io")
    print(a.model_dump())
    ok = Account.model_validate({"id": 7, "credits": 12})
    print(ok.id, ok.credits, ok.rate, ok.site, ok.email)
    try:
        Account.model_validate({"id": 0, "credits": -1, "rate": 0.0})
    except ValidationError as e:
        print(str(e))
    try:
        Account.model_validate({"id": 1, "site": "notaurl", "email": "nope"})
    except ValidationError as e:
        print(str(e))
    print(Account.model_json_schema())


if __name__ == "__main__":
    main()
