"""A same-named class in another module keeps its own layout (llvm struct keys are qualified)."""
from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Node:
    name: str
    kids: list[str]

    def label(self: Ref[Node]) -> str:
        return self.name + ":" + str(len(self.kids))
