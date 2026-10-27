from __future__ import annotations
from serpentine import Callable, Mut, dataclass


def note(msg: str) -> None:
    print("note:", msg)


def twice(n: int) -> None:
    print("twice:", n * 2)


@dataclass
class Tasks:
    items: list[Callable[[], None]] = []

    def add(self: Mut[Tasks], f: Callable[[], None]) -> None:
        self.items.append(f)


def run_all(t: Callable[[], None], u: Callable[[int], None]) -> None:
    t()
    u(21)


def main() -> None:
    who: str = "ada"
    k: int = 5
    ts: Tasks = Tasks()
    ts.add(lambda: note("hello " + who))
    ts.add(lambda: twice(k))
    ts.add(lambda: print("direct", k + 1))
    for f in ts.items:
        f()
    run_all(lambda: note("inline"), lambda x: twice(x + k))


if __name__ == "__main__":
    main()
