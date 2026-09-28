"""User-written __init__ constructors: normalization, validation, derived fields."""
from __future__ import annotations
from serpentine import Mut, Owned, Ref, dataclass, move


@dataclass
class Temperature:
    celsius: float
    label: str

    def __init__(self: Mut[Temperature], fahrenheit: float) -> None:
        if fahrenheit < -459.67:
            raise ValueError("below absolute zero")
        self.celsius = (fahrenheit - 32.0) * 5.0 / 9.0
        self.label = f"{self.celsius:.1f}C"

    def warmer(self: Ref[Temperature], other: Ref[Temperature]) -> bool:
        return self.celsius > other.celsius


@dataclass
class Bag:
    name: str
    items: list[int]
    total: int

    def __init__(self: Mut[Bag], name: str, items: Owned[list[int]]) -> None:
        cleaned: list[int] = []
        running: int = 0
        for v in items:
            if v > 0:
                cleaned.append(v)
                running = running + v
        self.name = name.strip().lower()
        self.items = move(cleaned)
        self.total = running


@dataclass
class Counter:
    start: int
    step: int

    def __init__(self: Mut[Counter], start: int = 0, step: int = 1) -> None:
        self.start = start
        self.step = step

    def at(self: Ref[Counter], n: int) -> int:
        return self.start + self.step * n


def main() -> None:
    t: Temperature = Temperature(212.0)
    print(t.celsius, t.label)
    c: Temperature = Temperature(32.0)
    print(c.label, t.warmer(c))
    try:
        bad: Temperature = Temperature(-500.0)
        print(bad.label)
    except ValueError as e:
        print("rejected:", e)

    b: Bag = Bag("  Fruits ", [3, -1, 4, 0, 5])
    print(b.name, b.items, b.total)
    print(b)

    z: Counter = Counter()
    print(z.at(10))
    k: Counter = Counter(5, step=3)
    print(k.at(4), k)


if __name__ == "__main__":
    main()
