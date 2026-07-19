"""Field-place narrowing: is-None tests on x.f (one level)."""
from __future__ import annotations
from serpentine import Mut, Ref, dataclass


@dataclass
class Task:
    title: str
    priority: int | None
    tags: list[str] | None


def describe(t: Ref[Task]) -> str:
    if t.priority is not None:
        return f"{t.title}!{t.priority + 1}"
    return f"{t.title}!?"


def tag_count(t: Ref[Task]) -> int:
    if t.tags is None:
        return 0
    return len(t.tags)


def escalate(t: Mut[Task]) -> None:
    if t.priority is not None:
        t.priority = t.priority + 10


def main() -> None:
    a: Task = Task("ship", 2, ["release", "urgent"])
    b: Task = Task("nap", None, None)
    print(describe(a), describe(b))
    print(tag_count(a), tag_count(b))
    escalate(a)
    escalate(b)
    print(describe(a), describe(b))
    if a.tags is not None:
        for tag in a.tags:
            print(tag)
    labels: list[str] = [describe(a) for _i in range(2)]
    print(labels)


if __name__ == "__main__":
    main()
