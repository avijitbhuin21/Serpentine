# serp-reject: SE201 unsupported-feature
"""Reject: asyncio.gather must be awaited directly (baton tasks, D45)."""
from __future__ import annotations

import asyncio


async def work(n: int) -> int:
    await asyncio.sleep(0)
    return n


async def amain() -> None:
    pending = asyncio.gather(work(1), work(2))  # E: SE201
    print(len(pending))


if __name__ == "__main__":
    asyncio.run(amain())
