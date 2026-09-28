"""_serp_asyncio CPython delegate: native builds use the baton task runtime instead.

The compiler intercepts `from _serp_asyncio import ...` (rtlib.py). Under CPython
these wrap the real asyncio primitives in handle tables so the `serp_asyncio`
facade dual-runs; the awaitable members are coroutine functions here and plain
(internally suspending) calls natively.
"""

import asyncio as _asyncio

__all__ = ["sleep", "current_task_id", "park", "wake", "wait_fd", "running",
           "ev_new", "ev_set", "ev_clear", "ev_is_set", "ev_wait",
           "lock_new", "lock_acquire", "lock_release", "lock_locked",
           "sem_new", "sem_acquire", "sem_release", "sem_locked", "sem_value",
           "q_new", "q_put", "q_get", "q_last", "q_qsize", "q_maxsize",
           "q_task_done", "q_join"]

_task_ids: dict = {}
_parked: dict = {}
_events: list = []
_locks: list = []
_sems: list = []
_queues: list = []
_last: list = [None]


async def sleep(secs):
    """Cooperative sleep."""
    await _asyncio.sleep(secs)


def current_task_id():
    """Small integer identifying the running task (0 = the asyncio.run main task)."""
    t = _asyncio.current_task()
    key = id(t)
    if key not in _task_ids:
        _task_ids[key] = len(_task_ids)
    return _task_ids[key]


async def park():
    """Suspend the current task until wake(id) is called for it."""
    fut = _asyncio.get_running_loop().create_future()
    _parked[current_task_id()] = fut
    await fut


def wake(tid):
    """Make a parked task runnable again."""
    fut = _parked.pop(tid, None)
    if fut is not None and not fut.done():
        fut.set_result(None)


async def wait_fd(h, write, timeout_ms):
    """Suspend until socket handle h is readable/writable; False on timeout."""
    import _serp_socket as _ss
    sock = _ss._socket_of(h)
    loop = _asyncio.get_running_loop()
    fut = loop.create_future()

    def _ready():
        if not fut.done():
            fut.set_result(True)
    if write:
        loop.add_writer(sock, _ready)
    else:
        loop.add_reader(sock, _ready)
    try:
        if timeout_ms is not None and timeout_ms >= 0:
            try:
                return await _asyncio.wait_for(fut, timeout_ms / 1000.0)
            except _asyncio.TimeoutError:
                return False
        return await fut
    finally:
        if write:
            loop.remove_writer(sock)
        else:
            loop.remove_reader(sock)


def running():
    """Whether the caller runs inside an event loop."""
    try:
        _asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def ev_new():
    """New asyncio.Event handle."""
    _events.append(_asyncio.Event())
    return len(_events)


def ev_set(h):
    """Event.set()."""
    _events[h - 1].set()


def ev_clear(h):
    """Event.clear()."""
    _events[h - 1].clear()


def ev_is_set(h):
    """Event.is_set()."""
    return _events[h - 1].is_set()


async def ev_wait(h):
    """Event.wait()."""
    return await _events[h - 1].wait()


def lock_new():
    """New asyncio.Lock handle."""
    _locks.append(_asyncio.Lock())
    return len(_locks)


async def lock_acquire(h):
    """Lock.acquire()."""
    return await _locks[h - 1].acquire()


def lock_release(h):
    """Lock.release()."""
    _locks[h - 1].release()


def lock_locked(h):
    """Lock.locked()."""
    return _locks[h - 1].locked()


def sem_new(value):
    """New asyncio.Semaphore handle."""
    if value < 0:
        raise ValueError("Semaphore initial value must be >= 0")
    _sems.append(_asyncio.Semaphore(value))
    return len(_sems)


async def sem_acquire(h):
    """Semaphore.acquire()."""
    return await _sems[h - 1].acquire()


def sem_release(h, bounded, initial):
    """Semaphore.release(); the bounded flag enforces BoundedSemaphore's ceiling."""
    s = _sems[h - 1]
    if bounded and s._value >= initial:
        raise ValueError("BoundedSemaphore released too many times")
    s.release()


def sem_locked(h):
    """Semaphore.locked()."""
    return _sems[h - 1].locked()


def sem_value(h):
    """Current semaphore counter."""
    return _sems[h - 1]._value


def q_new(maxsize):
    """New asyncio.Queue handle."""
    _queues.append(_asyncio.Queue(maxsize))
    return len(_queues)


async def q_put(h, item, nowait):
    """Queue.put / put_nowait (False when a nowait put finds the queue full)."""
    q = _queues[h - 1]
    if nowait:
        try:
            q.put_nowait(item)
        except _asyncio.QueueFull:
            return False
        return True
    await q.put(item)
    return True


async def q_get(h, nowait):
    """Queue.get / get_nowait; the item is read back through q_last()."""
    q = _queues[h - 1]
    if nowait:
        try:
            _last[0] = q.get_nowait()
        except _asyncio.QueueEmpty:
            return False
        return True
    _last[0] = await q.get()
    return True


def q_last():
    """The item delivered by the latest successful q_get on this task."""
    v = _last[0]
    _last[0] = None
    return v


def q_qsize(h):
    """Queue.qsize()."""
    return _queues[h - 1].qsize()


def q_maxsize(h):
    """Queue.maxsize."""
    return _queues[h - 1].maxsize


def q_task_done(h):
    """Queue.task_done()."""
    _queues[h - 1].task_done()


async def q_join(h):
    """Queue.join()."""
    await _queues[h - 1].join()
