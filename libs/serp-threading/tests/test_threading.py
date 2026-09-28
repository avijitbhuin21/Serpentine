"""serp-threading differential test: identical output under CPython and native builds."""
from __future__ import annotations
from serpentine import Owned, PyVal, move
from serp_threading import Thread, Timer, Lock, RLock, Event, Semaphore, BoundedSemaphore
from serp_threading import Condition, Barrier, BrokenBarrierError, local
from serp_threading import current_thread, main_thread, get_ident, active_count
from serp_queue_core import q_new, q_put, q_get, q_last, q_qsize
from serp_time import sleep


def worker(i: int, lk: Owned[Lock], qh: int) -> None:
    with lk:
        q_put(qh, i * i, 1, -1)


def waiter(ev: Owned[Event], qh: int) -> None:
    ev.wait(None)
    q_put(qh, "woke", 1, -1)


def barrier_party(bar: Owned[Barrier], qh: int) -> None:
    idx: int = bar.wait(None)
    q_put(qh, idx, 1, -1)


def consumer(cond: Owned[Condition], qh: int) -> None:
    with cond:
        cond.wait(None)
    q_put(qh, "notified", 1, -1)


def sem_user(i: int, sem: Owned[Semaphore], qh: int) -> None:
    with sem:
        q_put(qh, i, 1, -1)


def tls_user(i: int, tls: Owned[local], qh: int) -> None:
    tls.set("x", i)
    q_put(qh, tls.get("x"), 1, -1)


def fire(ev: Owned[Event]) -> None:
    ev.set()


def boom(n: int) -> None:
    raise ValueError(f"bad {n}")


def drain_ints(qh: int) -> list[int]:
    """Pop every queued int, sorted."""
    out: list[int] = []
    while q_qsize(qh) > 0:
        q_get(qh, 1, -1)
        out.append(int(q_last()))
    out.sort()
    return out


def drain_strs(qh: int) -> list[str]:
    """Pop every queued str in arrival order."""
    out: list[str] = []
    while q_qsize(qh) > 0:
        q_get(qh, 1, -1)
        out.append(str(q_last()))
    return out


def main() -> None:
    print("--- identity")
    print(current_thread().name, main_thread().name, get_ident() == main_thread().ident,
          current_thread().daemon, active_count())

    print("--- Lock")
    lk = Lock()
    print(lk.locked(), lk.acquire(), lk.locked(), lk.acquire(False), lk.acquire(True, 0.01))
    lk.release()
    print(lk.locked())
    try:
        lk.release()
    except RuntimeError as e:
        print("RuntimeError:", e)
    with lk:
        print("in with", lk.locked())
    print(lk.locked())
    try:
        lk.acquire(False, 1.0)
    except ValueError as e:
        print("ValueError:", e)

    print("--- RLock")
    rl = RLock()
    print(rl.acquire(), rl.acquire(), rl._is_owned(), rl.locked())
    rl.release()
    print(rl.locked())
    rl.release()
    print(rl.locked(), rl._is_owned())
    try:
        rl.release()
    except RuntimeError as e:
        print("RuntimeError:", e)

    print("--- Thread + Lock")
    qh: int = q_new(0, 0)
    t0 = Thread(target=worker, args=(0, lk, qh))
    t1 = Thread(target=worker, args=(1, lk, qh))
    t2 = Thread(target=worker, args=(2, lk, qh), name="two")
    t3 = Thread(target=worker, args=(3, lk, qh))
    print(t2.name, t0.ident, t0.is_alive(), t0.daemon)
    t0.start()
    t1.start()
    t2.start()
    t3.start()
    t0.join()
    t1.join()
    t2.join(5.0)
    t3.join(None)
    print(drain_ints(qh), t0.is_alive(), t0.ident is not None, active_count(), lk.locked())
    print(t0.name.startswith("Thread-"), t0.name.endswith("(worker)"))

    print("--- Event")
    ev = Event()
    print(ev.is_set(), ev.wait(0.01))
    w = Thread(target=waiter, args=(ev, qh), name="waiter", daemon=True)
    w.start()
    print(w.name, w.daemon, w.is_alive())
    ev.set()
    w.join()
    print(ev.is_set(), drain_strs(qh), w.is_alive())
    ev.clear()
    print(ev.is_set())

    print("--- Semaphore")
    sem = Semaphore(2)
    print(sem.acquire(), sem.acquire(), sem.acquire(False), sem.acquire(True, 0.01))
    sem.release(2)
    s0 = Thread(target=sem_user, args=(10, sem, qh))
    s1 = Thread(target=sem_user, args=(20, sem, qh))
    s0.start()
    s1.start()
    s0.join()
    s1.join()
    print(drain_ints(qh))
    bs = BoundedSemaphore(1)
    print(bs.acquire())
    bs.release()
    try:
        bs.release()
    except ValueError as e:
        print("ValueError:", e)
    try:
        Semaphore(-1)
    except ValueError as e:
        print("ValueError:", e)

    print("--- Condition")
    cond = Condition()
    c1 = Thread(target=consumer, args=(cond, qh))
    c2 = Thread(target=consumer, args=(cond, qh))
    c1.start()
    c2.start()
    sleep(0.3)
    with cond:
        cond.notify_all()
    c1.join()
    c2.join()
    print(drain_strs(qh))
    try:
        cond.wait(0.0)
    except RuntimeError as e:
        print("RuntimeError:", e)
    try:
        cond.notify()
    except RuntimeError as e:
        print("RuntimeError:", e)
    with cond:
        print("timed wait:", cond.wait(0.01))
    lk2 = Lock()
    cl = Condition(move(lk2))
    with cl:
        print("lock-backed:", cl.wait(0.01))
    try:
        cl.release()
    except RuntimeError as e:
        print("RuntimeError:", e)

    print("--- Barrier")
    bar = Barrier(3)
    print(bar.parties, bar.n_waiting, bar.broken)
    b1 = Thread(target=barrier_party, args=(bar, qh))
    b2 = Thread(target=barrier_party, args=(bar, qh))
    b1.start()
    b2.start()
    sleep(0.3)
    print(bar.n_waiting)
    q_put(qh, bar.wait(None), 1, -1)
    b1.join()
    b2.join()
    print(drain_ints(qh), bar.n_waiting)
    bar2 = Barrier(2, timeout=0.05)
    try:
        bar2.wait(None)
    except BrokenBarrierError:
        print("BrokenBarrierError", bar2.broken)
    bar2.reset()
    print(bar2.broken)
    bar2.abort()
    print(bar2.broken)

    print("--- local")
    tls = local()
    tls.set("x", "main")
    lt = Thread(target=tls_user, args=(7, tls, qh))
    lt.start()
    lt.join()
    print(tls.get("x"), drain_ints(qh), tls.has("y"), tls.get("y", 5))
    tls.delete("x")
    try:
        tls.delete("x")
    except AttributeError as e:
        print("AttributeError:", e)

    print("--- Timer")
    ev2 = Event()
    tm = Timer(0.05, fire, (ev2,))
    print(tm.is_alive())
    tm.start()
    print(ev2.wait(5.0))
    tm.join()
    ev2.clear()
    tm2 = Timer(30.0, fire, (ev2,))
    tm2.start()
    tm2.cancel()
    tm2.join()
    print(ev2.is_set(), tm2.is_alive())

    print("--- errors")
    tb = Thread(target=boom, args=(3,))
    tb.start()
    tb.join()
    print("boom joined", tb.is_alive())
    try:
        tb.start()
    except RuntimeError as e:
        print("RuntimeError:", e)
    tu = Thread(target=boom, args=(1,))
    try:
        tu.join()
    except RuntimeError as e:
        print("RuntimeError:", e)
    print(active_count())
    print("done")


if __name__ == "__main__":
    main()
