from __future__ import annotations

import asyncio


async def fetch(n: int) -> int:
    await asyncio.sleep(0.001)
    return n * 2


async def describe(n: int) -> str:
    v: int = await fetch(n)
    return "value=" + str(v)


async def amain() -> None:
    a: int = await fetch(3)
    b: int = await fetch(a)
    print(a, b)
    s: str = await describe(10)
    print(s)


if __name__ == "__main__":
    asyncio.run(amain())
