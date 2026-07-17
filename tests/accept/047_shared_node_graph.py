"""Shared class instances with a Weak back-edge (cycles leak by policy, D3)."""
from __future__ import annotations
from serpentine import Shared, Weak, dataclass, share, downgrade, upgrade


@dataclass
class Node:
    name: str
    next: Shared[Node] | None
    prev: Weak[Node] | None


def main() -> None:
    a: Shared[Node] = share(Node("a", None, None))
    b: Shared[Node] = share(Node("b", None, None))
    a.next = b
    b.prev = downgrade(a)
    print(a.name)
    nxt: Shared[Node] | None = a.next
    if nxt is not None:
        print(nxt.name)
        back: Weak[Node] | None = nxt.prev
        if back is not None:
            owner: Shared[Node] | None = upgrade(back)
            if owner is not None:
                print(owner.name)


if __name__ == "__main__":
    main()
