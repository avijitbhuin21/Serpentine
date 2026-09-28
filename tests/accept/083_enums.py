"""Accept: C-like Enum / IntEnum / StrEnum classes (LB6)."""

from enum import Enum, IntEnum, StrEnum


class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3


class Level(IntEnum):
    LOW = 10
    HIGH = 20


class Mode(StrEnum):
    READ = "r"
    WRITE = "w"


def describe(c: Color) -> str:
    """Name a color without a match statement."""
    if c == Color.RED:
        return "warm"
    if c == Color.BLUE:
        return "cool"
    return "other"


def main() -> None:
    c: Color = Color.GREEN
    print(c)
    print([c])
    print(c.name, c.value)
    print(c == Color.GREEN, c == Color.RED, c != Color.RED)
    print(describe(Color.RED), describe(Color.BLUE), describe(Color.GREEN))

    lv: Level = Level.HIGH
    print(lv)
    print([lv])
    print(lv.name, lv.value, lv.value + 1)

    m: Mode = Mode.WRITE
    print(m)
    print([m])
    print(m.name, m.value)

    picked: Color = Color(3)
    print(picked, picked.value)
    mode2: Mode = Mode("r")
    print(mode2.name)

    colors: list[Color] = [Color.RED, Color.BLUE]
    print(colors)
    print(len(colors), colors[0] == Color.RED)

    seen: set[Color] = {Color.RED, Color.RED, Color.BLUE}
    print(len(seen), Color.RED in seen, Color.GREEN in seen)

    counts: dict[Color, int] = {Color.RED: 2, Color.BLUE: 5}
    print(counts[Color.BLUE])

    print(f"{c} {c.name} {c.value}")
    print(str(c))

    try:
        bad: Color = Color(9)
        print(bad)
    except ValueError as e:
        print("ValueError:", e)


if __name__ == "__main__":
    main()
