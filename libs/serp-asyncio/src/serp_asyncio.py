"""serp-asyncio — drop-in `asyncio` facade for the parts the compiler does not own.

`asyncio.run` / `asyncio.sleep` / `asyncio.create_task` / `asyncio.gather` /
`asyncio.Task[T]` are language-level (docs/DECISIONS.md D45: baton-scheduled
tasks, CPython-identical FIFO order). Everything else reached through
`import asyncio` — `Event`, `Lock`, `Semaphore`, `BoundedSemaphore`, `Queue`,
`QueueEmpty`, `QueueFull` — resolves to this module. The primitives are
runtime-held handles (scalar classes), so they can be passed to tasks by copy.
Divergences: `Queue` items are `PyVal`, `Queue.maxsize` is a property, no
`Condition`/`wait_for`/`timeout`/cancellation, `async with` follows the same
`__aenter__ ... return self` rule as `with`.
"""
from __future__ import annotations
from serpentine import dataclass, Mut, Ref, PyVal
from _serp_asyncio import ev_new as _ev_new, ev_set as _ev_set, ev_clear as _ev_clear
from _serp_asyncio import ev_is_set as _ev_is_set, ev_wait as _ev_wait
from _serp_asyncio import lock_new as _lock_new, lock_acquire as _lock_acquire
from _serp_asyncio import lock_release as _lock_release, lock_locked as _lock_locked
from _serp_asyncio import sem_new as _sem_new, sem_acquire as _sem_acquire
from _serp_asyncio import sem_release as _sem_release, sem_locked as _sem_locked
from _serp_asyncio import q_new as _q_new, q_put as _q_put, q_get as _q_get, q_last as _q_last
from _serp_asyncio import q_qsize as _q_qsize, q_maxsize as _q_maxsize
from _serp_asyncio import q_task_done as _q_task_done, q_join as _q_join


class QueueEmpty(Exception):
    pass


class QueueFull(Exception):
    pass


@dataclass
class Event:
    _h: int

    def __init__(self: Mut[Event]) -> None:
        self._h = _ev_new()

    def is_set(self: Ref[Event]) -> bool:
        """Whether the flag is set."""
        return _ev_is_set(self._h)

    def set(self: Ref[Event]) -> None:
        """Set the flag and wake every waiter (in wait order)."""
        _ev_set(self._h)

    def clear(self: Ref[Event]) -> None:
        """Reset the flag."""
        _ev_clear(self._h)

    async def wait(self: Ref[Event]) -> bool:
        """Suspend until the flag is set."""
        return await _ev_wait(self._h)


@dataclass
class Lock:
    _h: int

    def __init__(self: Mut[Lock]) -> None:
        self._h = _lock_new()

    async def acquire(self: Ref[Lock]) -> bool:
        """Acquire the lock, suspending while another task holds it (FIFO)."""
        return await _lock_acquire(self._h)

    def release(self: Ref[Lock]) -> None:
        """Release the lock (RuntimeError when not acquired)."""
        _lock_release(self._h)

    def locked(self: Ref[Lock]) -> bool:
        """Whether the lock is held."""
        return _lock_locked(self._h)

    async def __aenter__(self: Ref[Lock]) -> Lock:
        await _lock_acquire(self._h)
        return self

    async def __aexit__(self: Ref[Lock], exc_type: None, exc: None, tb: None) -> None:
        _lock_release(self._h)


@dataclass
class Semaphore:
    _h: int
    _initial: int

    def __init__(self: Mut[Semaphore], value: int = 1) -> None:
        self._h = _sem_new(value)
        self._initial = value

    async def acquire(self: Ref[Semaphore]) -> bool:
        """Take one unit, suspending while the counter is zero (FIFO)."""
        return await _sem_acquire(self._h)

    def release(self: Ref[Semaphore]) -> None:
        """Return one unit and wake the next waiter."""
        _sem_release(self._h, 0, self._initial)

    def locked(self: Ref[Semaphore]) -> bool:
        """Whether acquire() would suspend."""
        return _sem_locked(self._h)

    async def __aenter__(self: Ref[Semaphore]) -> Semaphore:
        await _sem_acquire(self._h)
        return self

    async def __aexit__(self: Ref[Semaphore], exc_type: None, exc: None, tb: None) -> None:
        _sem_release(self._h, 0, self._initial)


@dataclass
class BoundedSemaphore:
    _h: int
    _initial: int

    def __init__(self: Mut[BoundedSemaphore], value: int = 1) -> None:
        self._h = _sem_new(value)
        self._initial = value

    async def acquire(self: Ref[BoundedSemaphore]) -> bool:
        """Take one unit, suspending while the counter is zero (FIFO)."""
        return await _sem_acquire(self._h)

    def release(self: Ref[BoundedSemaphore]) -> None:
        """Return one unit; ValueError above the initial value."""
        _sem_release(self._h, 1, self._initial)

    def locked(self: Ref[BoundedSemaphore]) -> bool:
        """Whether acquire() would suspend."""
        return _sem_locked(self._h)

    async def __aenter__(self: Ref[BoundedSemaphore]) -> BoundedSemaphore:
        await _sem_acquire(self._h)
        return self

    async def __aexit__(self: Ref[BoundedSemaphore], exc_type: None, exc: None, tb: None) -> None:
        _sem_release(self._h, 1, self._initial)


@dataclass
class Queue:
    _h: int

    def __init__(self: Mut[Queue], maxsize: int = 0) -> None:
        self._h = _q_new(maxsize)

    @property
    def maxsize(self: Ref[Queue]) -> int:
        """Capacity (0 = unbounded)."""
        return _q_maxsize(self._h)

    def qsize(self: Ref[Queue]) -> int:
        """Number of queued items."""
        return _q_qsize(self._h)

    def empty(self: Ref[Queue]) -> bool:
        """Whether the queue holds no items."""
        return _q_qsize(self._h) == 0

    def full(self: Ref[Queue]) -> bool:
        """Whether the queue is at capacity."""
        m: int = _q_maxsize(self._h)
        return m > 0 and _q_qsize(self._h) >= m

    async def put(self: Ref[Queue], item: PyVal) -> None:
        """Enqueue, suspending while full."""
        await _q_put(self._h, item, 0)

    def put_nowait(self: Ref[Queue], item: PyVal) -> None:
        """Enqueue without suspending (QueueFull when at capacity)."""
        if not _q_put(self._h, item, 1):
            raise QueueFull()

    async def get(self: Ref[Queue]) -> PyVal:
        """Dequeue, suspending while empty."""
        await _q_get(self._h, 0)
        return _q_last()

    def get_nowait(self: Ref[Queue]) -> PyVal:
        """Dequeue without suspending (QueueEmpty when nothing is queued)."""
        if not _q_get(self._h, 1):
            raise QueueEmpty()
        return _q_last()

    def task_done(self: Ref[Queue]) -> None:
        """Mark one dequeued item as processed."""
        _q_task_done(self._h)

    async def join(self: Ref[Queue]) -> None:
        """Suspend until every enqueued item has been marked done."""
        await _q_join(self._h)
