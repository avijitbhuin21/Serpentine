"""Cross-module base class: methods flatten into a subclass in another module."""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass


@dataclass
class Counter:
    count: int = 0

    def bump(self: Mut[Counter], n: int = 1) -> None:
        self.count += n

    def label(self: Ref[Counter]) -> str:
        return "counter"

    def check_positive(self: Ref[Counter]) -> None:
        if self.count <= 0:
            raise AssertionError(f"{self.count} is not positive")
