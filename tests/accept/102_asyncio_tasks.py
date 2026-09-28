from __future__ import annotations

import asyncio


async def worker(name: str, delay: float, n: int) -> int:
    print("start", name)
    await asyncio.sleep(delay)
    print("mid", name)
    await asyncio.sleep(0)
    print("end", name)
    return n * 10


async def fails(msg: str) -> str:
    await asyncio.sleep(0.01)
    raise ValueError(msg)


async def ticker(label: str, count: int) -> None:
    i: int = 0
    while i < count:
        print(label, i)
        await asyncio.sleep(0)
        i += 1


async def amain() -> None:
    t1: asyncio.Task[int] = asyncio.create_task(worker("a", 0.25, 1))
    t2: asyncio.Task[int] = asyncio.create_task(worker("b", 0.01, 2))
    print("created", t1.done(), t2.done())
    r1: int = await t1
    print("t1 ->", r1, t1.done())
    r2: int = await t2
    print("t2 ->", r2)

    rs: list[int] = await asyncio.gather(worker("c", 0.3, 3), worker("d", 0.02, 4))
    print("gather", rs)

    await asyncio.gather(ticker("x", 3), ticker("y", 2))

    tf: asyncio.Task[str] = asyncio.create_task(fails("boom"))
    try:
        s: str = await tf
        print("unexpected", s)
    except ValueError as e:
        print("caught", str(e))

    direct: int = await worker("e", 0.0, 5)
    print("direct", direct)


if __name__ == "__main__":
    asyncio.run(amain())
