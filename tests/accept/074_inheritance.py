"""Single inheritance: base fields and methods flatten into the subclass."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass


@dataclass
class Animal:
    name: str
    legs: int = 4

    def describe(self: Ref[Animal]) -> str:
        return f"{self.name} has {self.legs} legs"

    def sound(self: Ref[Animal]) -> str:
        return "..."

    def rename(self: Mut[Animal], name: str) -> None:
        self.name = name


@dataclass
class Dog(Animal):
    tricks: int = 0

    def sound(self: Ref[Dog]) -> str:
        return "woof"

    def learn(self: Mut[Dog]) -> None:
        self.tricks += 1


def main() -> None:
    d: Dog = Dog("rex")
    print(d.describe())
    print(d.sound())
    d.rename("bo")
    d.learn()
    print(d.describe())
    print(d.tricks)
    a: Animal = Animal("cat", 4)
    print(a.sound())


if __name__ == "__main__":
    main()
