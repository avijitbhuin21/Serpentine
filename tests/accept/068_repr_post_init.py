"""__repr__ override and __post_init__ validation on dataclasses."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass


@dataclass
class Frac:
    num: int
    den: int

    def __post_init__(self: Mut[Frac]) -> None:
        if self.den == 0:
            raise ValueError("zero denominator")
        if self.den < 0:
            self.num = -self.num
            self.den = -self.den

    def __repr__(self: Ref[Frac]) -> str:
        return f"Frac({self.num}/{self.den})"


@dataclass
class Tag:
    name: str

    def __str__(self: Ref[Tag]) -> str:
        return self.name

    def __repr__(self: Ref[Tag]) -> str:
        return f"<tag {self.name}>"


def main() -> None:
    a: Frac = Frac(1, 2)
    print(a)
    b: Frac = Frac(3, -6)
    print(b)
    fs: list[Frac] = [Frac(1, 3), Frac(2, 4)]
    print(fs)
    print(f"a={a!r} b={b!r}")
    try:
        c: Frac = Frac(1, 0)
        print(c)
    except ValueError as e:
        print("caught:", e)
    t: Tag = Tag("x")
    print(t)
    print(f"{t} {t!r}")
    ts: list[Tag] = [Tag("u"), Tag("v")]
    print(ts)
    d: dict[str, Frac] = {"half": Frac(1, 2)}
    print(d)


if __name__ == "__main__":
    main()
