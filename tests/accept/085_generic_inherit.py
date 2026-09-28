"""Generic classes that also inherit a plain @dataclass base."""
from __future__ import annotations
from typing import Generic, TypeVar
from serpentine import PyVal, Ref, dataclass, fields_build, fields_json, fields_of, move

T = TypeVar("T")
K = TypeVar("K")


@dataclass
class Envelope:
    ok: bool
    note: str

    def banner(self: Ref[Envelope]) -> str:
        return f"[{self.note}]"


@dataclass
class Page(Envelope, Generic[T]):
    items: list[T]
    total: int

    def size(self: Ref[Page[T]]) -> int:
        return len(self.items)

    def first(self: Ref[Page[T]]) -> T:
        return self.items[0]


@dataclass
class Pair(Generic[K, T]):
    key: K
    value: T


def describe(p: Ref[Page[int]]) -> str:
    return f"{p.banner()} {p.size()} of {p.total}"


def main() -> None:
    nums: list[int] = [1, 2, 3]
    p: Page[int] = Page(True, "nums", move(nums), 3)
    print(p.ok, p.note, p.items, p.total)
    print(p.banner(), p.size(), p.first())
    print(describe(p))

    words: list[str] = ["a", "b"]
    q: Page[str] = Page(False, "words", move(words), 2)
    print(q.banner(), q.size(), q.first())
    print(q)

    pr: Pair[str, int] = Pair("age", 7)
    print(pr.key, pr.value)

    print(fields_of(p))
    print(fields_json(Page[int]))
    src: dict[str, PyVal] = {"ok": True, "note": "built", "items": [4, 5], "total": 2}
    r: Page[int] = fields_build(Page[int], src)
    print(r.note, r.items, r.total, r.size())
    ssrc: dict[str, PyVal] = {"ok": False, "note": "s", "items": ["z"], "total": 1}
    sp: Page[str] = fields_build(Page[str], ssrc)
    print(sp.first(), fields_of(sp))
    try:
        bad = fields_build(Page[int], {"ok": True, "note": "n", "items": ["x"], "total": 0})
        print("unreachable", bad.total)
    except TypeError as e:
        print("rejected:", e)


if __name__ == "__main__":
    main()
