from __future__ import annotations

import asyncio

from serpentine import Owned, PyVal, Ref


async def waiter(name: str, ev: Owned[asyncio.Event]) -> str:
    print("waiting", name)
    ok: bool = await ev.wait()
    print("woke", name, ok)
    return name


async def setter(ev: Owned[asyncio.Event]) -> None:
    await asyncio.sleep(0.02)
    print("setting", ev.is_set())
    ev.set()
    print("set", ev.is_set())


async def locker(name: str, lock: Owned[asyncio.Lock], hold: float) -> None:
    print("acquire", name)
    async with lock:
        print("holding", name, lock.locked())
        await asyncio.sleep(hold)
    print("released", name)


async def barge(lock: Owned[asyncio.Lock]) -> None:
    await asyncio.sleep(0.03)
    print("barge acquire", lock.locked())
    await lock.acquire()
    print("barge holding")
    lock.release()
    print("barge released")


async def sem_user(name: str, sem: Owned[asyncio.Semaphore]) -> None:
    async with sem:
        print("in", name)
        await asyncio.sleep(0.02)
    print("out", name)


async def producer(q: Owned[asyncio.Queue], n: int) -> None:
    i: int = 0
    while i < n:
        await q.put(i)
        print("put", i, q.qsize())
        i += 1
    await q.put("stop")


async def consumer(name: str, q: Ref[asyncio.Queue]) -> int:
    total: int = 0
    while True:
        item: PyVal = await q.get()
        q.task_done()
        if item == "stop":
            print("consumer", name, "stopping")
            return total
        v: int = int(item)
        total += v
        print("got", name, v)
        await asyncio.sleep(0.01)
    raise OSError("unreachable")


async def amain() -> None:
    ev: asyncio.Event = asyncio.Event()
    st: asyncio.Task[None] = asyncio.create_task(setter(ev))
    r: list[str] = await asyncio.gather(waiter("w1", ev), waiter("w2", ev))
    await st
    print("gather", r[0], r[1], ev.is_set())
    ev.clear()
    print("cleared", ev.is_set())

    lock: asyncio.Lock = asyncio.Lock()
    print("locked?", lock.locked())
    await asyncio.gather(locker("l1", lock, 0.05), locker("l2", lock, 0.02), barge(lock))
    print("locked?", lock.locked())
    try:
        lock.release()
    except RuntimeError as e:
        print("release error:", str(e))

    sem: asyncio.Semaphore = asyncio.Semaphore(2)
    await asyncio.gather(sem_user("s1", sem), sem_user("s2", sem), sem_user("s3", sem))
    print("sem locked?", sem.locked())

    bs: asyncio.BoundedSemaphore = asyncio.BoundedSemaphore(1)
    try:
        bs.release()
    except ValueError as e:
        print("bounded:", str(e))

    q: asyncio.Queue = asyncio.Queue(2)
    print("maxsize", q.maxsize, q.empty(), q.full())
    pt: asyncio.Task[None] = asyncio.create_task(producer(q, 5))
    total: int = await consumer("c", q)
    await pt
    print("total", total, q.empty())
    q.put_nowait("x")
    q.put_nowait("y")
    try:
        q.put_nowait("z")
    except asyncio.QueueFull:
        print("full!")
    print(q.get_nowait(), q.get_nowait())
    try:
        q.get_nowait()
    except asyncio.QueueEmpty:
        print("empty!")


if __name__ == "__main__":
    asyncio.run(amain())
