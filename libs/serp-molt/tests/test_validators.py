"""serp-molt: @field_validator / @model_validator and model_config."""
from __future__ import annotations

from serp_molt import (BaseModel, ConfigDict, Field, ValidationError, field_validator,
                       model_validator)
from serpentine import PyVal, Ref


class Account(BaseModel):
    name: str = Field(min_length=2)
    email: str = ""
    balance: int = 0

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: PyVal) -> PyVal:
        return str(v).strip()

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: PyVal) -> PyVal:
        if len(str(v)) > 0 and not ("@" in str(v)):
            raise ValueError("email must contain @")
        return str(v).lower()

    @model_validator(mode="before")
    @classmethod
    def fill_email(cls, data: PyVal) -> PyVal:
        if not ("email" in data):
            return data
        if str(data["email"]) == "none":
            raise ValueError("email 'none' is not allowed")
        return data

    @model_validator(mode="after")
    def check_balance(self: Ref[Account]) -> None:
        if self.balance < 0:
            raise ValueError("balance may not be negative")


class Sub(Account):
    tag: str = "sub"

    @field_validator("tag")
    @classmethod
    def upper_tag(cls, v: PyVal) -> PyVal:
        return str(v).upper()


def show(label: str, e: str) -> None:
    """Print a labelled validation error message."""
    print(label)
    print(e)


def main() -> None:
    a: Account = Account.model_validate({"name": "  ada  ", "email": "ADA@X.IO",
                                         "balance": 5})
    print(a.name, a.email, a.balance)

    b: Account = Account.model_validate({"name": " bob ", "email": " B@X.IO "})
    print(b.name, b.email, b.balance)

    try:
        Account.model_validate({"name": "eve", "email": "nope"})
    except ValidationError as e1:
        show("bad-email", str(e1))

    try:
        Account.model_validate({"name": "eve", "email": "none"})
    except ValidationError as e2:
        show("model-before", str(e2))

    try:
        Account.model_validate({"name": "eve", "balance": -1})
    except ValidationError as e3:
        show("model-after", str(e3))

    try:
        Account.model_validate({"name": "eve", "extra": 1})
    except ValidationError as e4:
        show("extra-forbidden", str(e4))

    try:
        Account.model_validate({"name": "x"})
    except ValidationError as e5:
        show("too-short", str(e5))

    s: Sub = Sub.model_validate({"name": " zoe ", "tag": "vip"})
    print(s.name, s.tag, s.balance)

    try:
        Sub.model_validate({"name": "zoe", "balance": -2})
    except ValidationError as e6:
        show("inherited-after", str(e6))

    raw: Account = Account.model_validate_json('{"name": " raw ", "balance": 3}')
    print(raw.name)
    print(Sub.model_json_schema()["title"])


if __name__ == "__main__":
    main()
