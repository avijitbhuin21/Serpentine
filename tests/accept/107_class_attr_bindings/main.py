from __future__ import annotations
from serpentine import Ref, dataclass
from zonelib import Zone, Span, default_width


@dataclass
class Holder:
    zone: Zone | None = None

    def lo(self: Ref[Holder]) -> int:
        if self.zone is None:
            return -1
        return self.zone.span.lo

    def zone_or_none(self: Ref[Holder]) -> Zone | None:
        if self.zone is None:
            return None
        return Zone(self.zone.name, Span(self.zone.span.lo, self.zone.span.hi))


def main() -> None:
    print(Zone.default, Zone.wide.span)
    print(default_width(), Zone.wide.span.hi)
    h: Holder = Holder(Zone.wide)
    e: Holder = Holder()
    print(h.lo(), e.lo())
    print(h.zone_or_none(), e.zone_or_none())
    maybe: Span | None = Span(3, 4)
    print(maybe, f"{maybe}")


if __name__ == "__main__":
    main()
