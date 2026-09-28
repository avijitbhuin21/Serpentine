"""Accept: two modules define a class named Node with different field layouts."""
from __future__ import annotations
from serpentine import Ref, dataclass, move

from treelib import Node as TreeNode


@dataclass
class Node:
    tag: str
    count: int

    def label(self: Ref[Node]) -> str:
        return self.tag + "=" + str(self.count)


def main() -> None:
    kids: list[str] = ["a", "b"]
    t: TreeNode = TreeNode("root", move(kids))
    n: Node = Node("here", 7)
    print(t.label())
    print(n.label())
    print(t.name, len(t.kids), n.tag, n.count)
    print(n == Node("here", 7))


if __name__ == "__main__":
    main()
