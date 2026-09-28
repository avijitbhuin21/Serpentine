"""serp-queue — drop-in `queue` facade over serp_queue_core.

Thread-safe FIFO/LIFO queues whose items are dynamic values (PyVal: None, bool,
int, float, str, bytes, lists and dicts of those) deep-copied across the thread
boundary — the sharing channel for serp_threading. Stdlib names and shapes:
`Queue(maxsize=0)`, `LifoQueue`, `put/get` with block/timeout, `put_nowait`,
`get_nowait`, `qsize/empty/full`, `task_done/join`, `Empty`/`Full`.
Divergences: no `PriorityQueue`/`SimpleQueue`; items are copies (mutating a
fetched list does not affect the producer's); `qsize()` is exact.
"""
from __future__ import annotations
from serpentine import dataclass, Mut, Ref, PyVal
from serp_queue_core import q_new as _q_new, q_put as _q_put, q_get as _q_get
from serp_queue_core import q_last as _q_last, q_qsize as _q_qsize
from serp_queue_core import q_task_done as _q_task_done, q_join as _q_join


class Empty(Exception):
    pass


class Full(Exception):
    pass


def _timeout_ms(block: bool, timeout: float | None) -> int:
    """Translate (block, timeout) into runtime milliseconds (0 = try, -1 = forever)."""
    if not block:
        return 0
    if timeout is None:
        return -1
    if timeout < 0.0:
        raise ValueError("'timeout' must be a non-negative number")
    return int(timeout * 1000.0)


@dataclass
class Queue:
    _h: int
    maxsize: int

    def __init__(self: Mut[Queue], maxsize: int = 0) -> None:
        self.maxsize = maxsize
        self._h = _q_new(maxsize, 0)

    def put(self: Ref[Queue], item: PyVal, block: bool = True, timeout: float | None = None) -> None:
        """Enqueue a copy of item, blocking while full (Full when non-blocking/timed out)."""
        if not _q_put(self._h, item, 1 if block else 0, _timeout_ms(block, timeout)):
            raise Full("")

    def put_nowait(self: Ref[Queue], item: PyVal) -> None:
        """Enqueue without blocking (Full when the queue is full)."""
        self.put(item, False, None)

    def get(self: Ref[Queue], block: bool = True, timeout: float | None = None) -> PyVal:
        """Dequeue the next item, blocking while empty (Empty when non-blocking/timed out)."""
        if not _q_get(self._h, 1 if block else 0, _timeout_ms(block, timeout)):
            raise Empty("")
        return _q_last()

    def get_nowait(self: Ref[Queue]) -> PyVal:
        """Dequeue without blocking (Empty when the queue is empty)."""
        return self.get(False, None)

    def qsize(self: Ref[Queue]) -> int:
        """Number of queued items."""
        return _q_qsize(self._h)

    def empty(self: Ref[Queue]) -> bool:
        """Whether the queue has no items."""
        return _q_qsize(self._h) == 0

    def full(self: Ref[Queue]) -> bool:
        """Whether the queue holds maxsize items (never for unbounded queues)."""
        if self.maxsize <= 0:
            return False
        return _q_qsize(self._h) >= self.maxsize

    def task_done(self: Ref[Queue]) -> None:
        """Mark one previously fetched item as processed."""
        _q_task_done(self._h)

    def join(self: Ref[Queue]) -> None:
        """Block until every item has been fetched and marked done."""
        _q_join(self._h)


@dataclass
class LifoQueue:
    _h: int
    maxsize: int

    def __init__(self: Mut[LifoQueue], maxsize: int = 0) -> None:
        self.maxsize = maxsize
        self._h = _q_new(maxsize, 1)

    def put(self: Ref[LifoQueue], item: PyVal, block: bool = True, timeout: float | None = None) -> None:
        """Push a copy of item, blocking while full."""
        if not _q_put(self._h, item, 1 if block else 0, _timeout_ms(block, timeout)):
            raise Full("")

    def put_nowait(self: Ref[LifoQueue], item: PyVal) -> None:
        """Push without blocking."""
        self.put(item, False, None)

    def get(self: Ref[LifoQueue], block: bool = True, timeout: float | None = None) -> PyVal:
        """Pop the most recent item, blocking while empty."""
        if not _q_get(self._h, 1 if block else 0, _timeout_ms(block, timeout)):
            raise Empty("")
        return _q_last()

    def get_nowait(self: Ref[LifoQueue]) -> PyVal:
        """Pop without blocking."""
        return self.get(False, None)

    def qsize(self: Ref[LifoQueue]) -> int:
        """Number of queued items."""
        return _q_qsize(self._h)

    def empty(self: Ref[LifoQueue]) -> bool:
        """Whether the queue has no items."""
        return _q_qsize(self._h) == 0

    def full(self: Ref[LifoQueue]) -> bool:
        """Whether the queue holds maxsize items."""
        if self.maxsize <= 0:
            return False
        return _q_qsize(self._h) >= self.maxsize

    def task_done(self: Ref[LifoQueue]) -> None:
        """Mark one fetched item as processed."""
        _q_task_done(self._h)

    def join(self: Ref[LifoQueue]) -> None:
        """Block until every item has been marked done."""
        _q_join(self._h)
