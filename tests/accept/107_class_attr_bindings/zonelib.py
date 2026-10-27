from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Span:
    lo: int
    hi: int

    def __str__(self: Ref[Span]) -> str:
        return f"{self.lo}..{self.hi}"


@dataclass
class Zone:
    name: str
    span: Span

    def __str__(self: Ref[Zone]) -> str:
        return f"zone {self.name}"


Zone.default = Zone("default", Span(0, 10))
Zone.wide = Zone("wide", Span(-100, 100))


def default_width() -> int:
    """Width of the default zone, read through the class attribute inside the module."""
    z: Zone = Zone.default
    return z.span.hi - z.span.lo
