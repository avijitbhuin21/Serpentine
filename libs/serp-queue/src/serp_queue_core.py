"""serp-queue-core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_queue_core import ...` (rtlib.py); under
CPython these mirror the handle-based, deep-copying queue table in prelude.rs
on top of stdlib `queue`.
"""

import copy as _copy
import queue as _queue
import threading as _threading

__all__ = ["q_new", "q_put", "q_get", "q_last", "q_qsize", "q_task_done", "q_join"]

_QUEUES = []
_last = _threading.local()


def _get(h):
    """Resolve a 1-based queue handle."""
    if h < 1 or h > len(_QUEUES):
        raise ValueError("invalid queue handle")
    return _QUEUES[h - 1]


def q_new(maxsize, lifo):
    """Create a FIFO (or LIFO) queue; returns its handle."""
    _QUEUES.append(_queue.LifoQueue(maxsize) if lifo else _queue.Queue(maxsize))
    return len(_QUEUES)


def q_put(h, item, block, timeout_ms):
    """Enqueue a deep copy of item; False when the queue stayed full."""
    q = _get(h)
    try:
        if not block or timeout_ms == 0:
            q.put(_copy.deepcopy(item), block=False)
        else:
            q.put(_copy.deepcopy(item), timeout=None if timeout_ms < 0 else timeout_ms / 1000.0)
        return True
    except _queue.Full:
        return False


def q_get(h, block, timeout_ms):
    """Dequeue into the thread-local slot read by q_last(); False when empty."""
    q = _get(h)
    try:
        if not block or timeout_ms == 0:
            item = q.get(block=False)
        else:
            item = q.get(timeout=None if timeout_ms < 0 else timeout_ms / 1000.0)
    except _queue.Empty:
        return False
    _last.item = item
    return True


def q_last():
    """The item fetched by the calling thread's last successful q_get()."""
    item = getattr(_last, "item", None)
    _last.item = None
    return item


def q_qsize(h):
    """Approximate number of items."""
    return _get(h).qsize()


def q_task_done(h):
    """Mark one fetched item as processed."""
    _get(h).task_done()


def q_join(h):
    """Block until every enqueued item has been marked done."""
    _get(h).join()
