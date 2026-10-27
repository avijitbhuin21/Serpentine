"""Lambdas capturing non-Copy values (lists, dicts, dataclasses, list[str]): the capture is a
copy, which matches CPython's by-reference closure because the checker forbids mutating,
moving or rebinding the captured variable afterwards and mutating it inside the lambda."""
from __future__ import annotations
from serpentine import Callable, Ref, dataclass


@dataclass
class User:
    name: str
    roles: list[str]

    def describe(self: Ref[User]) -> str:
        return self.name + "[" + ",".join(self.roles) + "]"


def total(xs: Ref[list[int]]) -> int:
    t: int = 0
    for x in xs:
        t += x
    return t


def apply_all(fs: Ref[list[Callable[[int], int]]], v: int) -> list[int]:
    return [f(v) for f in fs]


def call_twice(f: Callable[[], str]) -> str:
    return f() + " / " + f()


def make_greeter(u: Ref[User]) -> Callable[[str], str]:
    snapshot: User = User(u.name, [r for r in u.roles])
    return lambda greeting: greeting + ", " + snapshot.describe()


def main() -> None:
    weights: list[int] = [3, 1, 4, 1, 5]
    scale: Callable[[int], int] = lambda v: v * total(weights)
    shift: Callable[[int], int] = lambda v: v + len(weights) + weights[2]
    fs: list[Callable[[int], int]] = [scale, shift]
    print(apply_all(fs, 2), apply_all(fs, 10))
    print(total(weights), weights)

    admin: User = User("ada", ["admin", "ops"])
    who: Callable[[], str] = lambda: admin.describe() + " has " + str(len(admin.roles))
    print(call_twice(who))
    print(admin.name, admin.roles[0])

    prices: dict[str, float] = {"pen": 1.5, "ink": 4.25}
    cost: Callable[[str], float] = lambda item: prices[item] * 2.0 if item in prices else -1.0
    print(cost("pen"), cost("ink"), cost("cap"), len(prices))

    tags: list[str] = ["x", "y"]
    joiner: Callable[[str], str] = lambda sep: sep.join(tags)
    print(joiner("-"), joiner("+"), tags)

    greet: Callable[[str], str] = make_greeter(admin)
    print(greet("hi"), greet("bye"))


if __name__ == "__main__":
    main()
