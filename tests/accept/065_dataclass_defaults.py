"""Accept: literal dataclass field defaults with positional and keyword construction."""
from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Config:
    host: str
    port: int = 8080
    debug: bool = False
    label: str = "srv"


def show(c: Ref[Config]) -> None:
    print(c.host, c.port, c.debug, c.label)


def main() -> None:
    a: Config = Config("a.example")
    show(a)
    b: Config = Config("b.example", 9000)
    show(b)
    c: Config = Config("c.example", 9001, True, "x")
    show(c)
    d: Config = Config("d.example", debug=True)
    show(d)
    e: Config = Config("e.example", label="z", port=81)
    show(e)
    print(a)


if __name__ == "__main__":
    main()
