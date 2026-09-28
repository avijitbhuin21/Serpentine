# serp-reject: SE201 unsupported-feature
"""Reject: calling an async function without awaiting it (eager coroutines, D14)."""

import asyncio


async def fetch(n: int) -> int:
    return n * 2


def main() -> None:
    x: int = fetch(3)  # E: SE201
    print(x)


if __name__ == "__main__":
    main()
