"""serp-molt SecretStr fields: masked dumps, get_secret_value, and the password schema."""
from __future__ import annotations

from serp_molt import BaseModel, Field, SecretStr, ValidationError
from serpentine import PyVal


class Account(BaseModel):
    user: str
    password: SecretStr
    token: SecretStr = Field(description="api token")


def main() -> None:
    a: Account = Account.model_validate({"user": "ada", "password": "hunter2",
                                         "token": "t-123"})
    print(a.user)
    print(a.password.get_secret_value())
    print(str(a.password))
    print(a.model_dump())
    print(a.model_dump_json())

    errs: list[PyVal] = Account.model_validate_errors({"user": "ada", "password": 5,
                                                       "token": "t"})
    for e in errs:
        print(e["type"], e["loc"], e["msg"])

    caught: bool = False
    try:
        bad: Account = Account.model_validate({"user": "ada", "password": "p"})
    except ValidationError as exc:
        caught = True
        print(str(exc))
    print(caught)

    schema: PyVal = Account.model_json_schema()
    print(schema["properties"]["password"])
    print(schema["properties"]["token"])
    print(schema["required"])


if __name__ == "__main__":
    main()
