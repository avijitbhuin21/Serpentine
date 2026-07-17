"""Classes as function parameters: Ref/Mut/Owned conventions apply to instances."""
from __future__ import annotations
from serpentine import Owned, Ref, Mut, dataclass, move


@dataclass
class Account:
    owner: str
    balance: int


def describe(a: Ref[Account]) -> str:
    return f"{a.owner}: {a.balance}"


def deposit(a: Mut[Account], amount: int) -> None:
    a.balance += amount


def close(a: Owned[Account]) -> int:
    return a.balance


def main() -> None:
    acct: Account = Account("ada", 100)
    print(describe(acct))
    deposit(acct, 50)
    print(describe(acct))
    final: int = close(move(acct))
    print(final)


if __name__ == "__main__":
    main()
