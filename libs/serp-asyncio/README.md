# serp-asyncio

Drop-in `asyncio` for Serpentine (docs/DECISIONS.md **D45**).

```python
import asyncio

async def worker(name: str, q: Owned[asyncio.Queue]) -> int: ...

async def amain() -> None:
    q: asyncio.Queue = asyncio.Queue(10)
    t: asyncio.Task[int] = asyncio.create_task(worker("a", q))
    rs: list[int] = await asyncio.gather(worker("b", q), worker("c", q))
    n: int = await t
    lock: asyncio.Lock = asyncio.Lock()
    async with lock:
        await asyncio.sleep(0.01)

asyncio.run(amain())
```

## What lives where

| `asyncio.` member | where |
| --- | --- |
| `run`, `sleep`, `create_task(f(args), name=)`, `gather(c1(), c2())`, `Task[T]`, `await task`, `task.done()`, `TimeoutError` | compiler + runtime (no package needed) |
| `Event`, `Lock`, `Semaphore`, `BoundedSemaphore`, `Queue`, `QueueEmpty`, `QueueFull` | this package (`import asyncio` routes them to `serp_asyncio`) |

Tasks are OS threads that pass a baton: exactly one runs at a time and scheduling replays
CPython's `_run_once` (FIFO ready queue, I/O-ready tasks, then expired timers), so a program
prints the same interleaving under CPython and natively. The primitives are runtime-held
handles, so they can be passed to tasks as `Owned[asyncio.Queue]` etc.

## Divergences

- No cancellation (`cancel()`, `CancelledError`), `Task.result()`, `wait_for`, `timeout`,
  `Condition`, `async for`, `gather(*coros)`, `return_exceptions=`.
- `gather` must be the whole right-hand side of an assignment / return or a bare statement,
  and all its coroutines must return the same type (a `list[T]`).
- A task may be awaited once; `create_task` takes a direct call to an `async def` function
  with Send arguments (int/float/bool/str/bytes/scalar classes such as the primitives here).
- One event loop per process; tasks still pending when `asyncio.run` returns are abandoned.
- `Queue` items are `PyVal`; `Queue.maxsize` is a property.
- Keep sleeps that must order deterministically ≥ 20 ms apart: Windows CPython's monotonic
  clock has 15.6 ms resolution and fires close timers together.
- Under CPython the socket async mode used by Fang/Venom is a no-op — network I/O there
  blocks the loop (results match, interleavings need not).
