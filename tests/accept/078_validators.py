"""Validator-hook intrinsics: hooks_json, run_hook, run_hook_self and model_config."""

from __future__ import annotations

from serpentine import (ConfigDict, PyVal, Ref, dataclass, field_validator, fields_json,
                        hooks_json, model_validator, run_hook, run_hook_self)


@dataclass
class Account:
    name: str
    balance: int = 0

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("name", mode="before")
    @classmethod
    def trim(cls, v: PyVal) -> PyVal:
        return str(v).strip()

    @field_validator("balance")
    @classmethod
    def positive(cls, v: PyVal) -> PyVal:
        if int(v) < 0:
            raise ValueError("balance may not be negative")
        return v

    @model_validator(mode="after")
    def label(self: Ref[Account]) -> None:
        print("checked", self.name, self.balance)


@dataclass
class Sub(Account):
    tag: str = "sub"

    @field_validator("tag")
    @classmethod
    def upper(cls, v: PyVal) -> PyVal:
        return str(v).upper()


def main() -> None:
    print(hooks_json(Account))
    print(hooks_json(Sub))
    print(fields_json(Account))
    print(run_hook(Account, "trim", "  ada  "))
    print(run_hook(Account, "positive", 4))
    print(run_hook(Sub, "upper", "vip"))
    a = Account(name="ada", balance=2)
    run_hook_self(a, "label")
    s = Sub(name="zoe", balance=1, tag="VIP")
    run_hook_self(s, "label")
    try:
        print(run_hook(Account, "positive", -1))
    except ValueError as e:
        print("rejected:", e)


if __name__ == "__main__":
    main()
