"""Frozen dataclasses and the __setattr__ attribute-write hook with fields_set."""

from __future__ import annotations

from serpentine import (Mut, PyVal, dataclass, fields_of, fields_set, pyval_kind)


@dataclass(frozen=True)
class Point:
    x: int
    y: int


class Point3(Point):
    z: int


@dataclass
class Account:
    name: str
    balance: int

    def __setattr__(self: Mut[Account], name: str, value: PyVal) -> None:
        if name == "balance" and pyval_kind(value) == "int" and int(value) < 0:
            raise ValueError("balance must not be negative")
        fields_set(self, name, value)


def main() -> None:
    p = Point(x=1, y=2)
    print("point", p.x + p.y)
    q = Point3(x=3, y=4, z=5)
    print("point3", q.x + q.y + q.z)
    d: dict[str, PyVal] = fields_of(p)
    print("dumped", len(d))

    a = Account(name="ada", balance=10)
    a.balance = 25
    print("balance", a.balance)
    a.name = "grace"
    print("name", a.name)
    try:
        a.balance = -5
    except ValueError:
        print("rejected")
    print("still", a.balance)
    try:
        fields_set(a, "nope", 1)
    except ValueError:
        print("unknown field")


if __name__ == "__main__":
    main()
