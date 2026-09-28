"""Accept: Thread/Timer objects (D9 v2), scalar-class Send args, __enter__ side effects."""
from __future__ import annotations

from serpentine import Mut, Owned, Ref, Thread, Timer, dataclass


@dataclass
class Guard:
    depth: int
    enters: int

    def __enter__(self: Ref[Guard]) -> Guard:
        print("entering at depth", self.depth)
        return self

    def __exit__(self: Mut[Guard], exc_type: None, exc: None, tb: None) -> None:
        self.enters = self.enters + 1
        print("exited; enters =", self.enters)


@dataclass
class Job:
    id: int
    scale: float
    urgent: bool


def worker(tag: str, n: int, job: Owned[Job]) -> None:
    """Print a summary computed from copied arguments."""
    total: float = 0.0
    for i in range(n):
        total = total + float(i) * job.scale
    print(f"{tag}: job={job.id} urgent={job.urgent} total={total}")


def quiet(n: int) -> None:
    """Do nothing observable."""
    x: int = n * 2
    x = x + 1


def boom(n: int) -> None:
    raise ValueError(f"bad {n}")


def main() -> None:
    """Exercise construction, start/join, attributes, timers and error paths."""
    g = Guard(1, 0)
    with g:
        print("inside", g.depth)
    with g:
        print("inside again")
    print(g.enters)

    job = Job(7, 0.5, True)
    t = Thread(target=worker, args=("w1", 4, job), name="worker-1")
    print(t.name, t.is_alive(), t.ident is None, t.daemon)
    t.start()
    t.join()
    print(t.is_alive(), t.ident is not None, job.id)

    t2 = Thread(target=worker, args=("w2", 3, job), daemon=True)
    print(t2.name.startswith("Thread-"), t2.name.endswith("(worker)"), t2.daemon)
    t2.start()
    t2.join(5.0)
    print(t2.is_alive())

    tm = Timer(0.02, quiet, (1,))
    print(tm.is_alive(), tm.name.startswith("Thread-"))
    tm.start()
    tm.join()
    print(tm.is_alive())
    tm2 = Timer(30.0, quiet, (2,))
    tm2.start()
    tm2.cancel()
    tm2.join()
    print(tm2.is_alive())

    tb = Thread(target=boom, args=(9,))
    tb.start()
    tb.join()
    print("boom finished", tb.is_alive())
    try:
        tb.start()
    except RuntimeError as e:
        print("RuntimeError:", e)
    tu = Thread(target=quiet, args=(0,))
    try:
        tu.join()
    except RuntimeError as e:
        print("RuntimeError:", e)
    print("done")


if __name__ == "__main__":
    main()
