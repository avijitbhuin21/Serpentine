"""serp-threading — drop-in `threading` facade (D9 v2).

`Thread`/`Timer` are language intrinsics (re-exported from `serpentine`): the
target must be a named module function whose parameters are Send-by-copy
(int/float/bool/str/bytes or classes made of those scalars, declared `Owned[...]`),
`args=` is a tuple literal, and threads are joined at program exit like CPython.
The sync primitives (`Lock`, `RLock`, `Event`, `Semaphore`, `BoundedSemaphore`,
`Condition`, `Barrier`) are runtime-held handles that may be passed to threads;
`local()` is a thread-local key/value store. Divergences: no shared mutable
objects across threads (use serp_queue), `local()` uses get/set/has/delete
instead of attribute access, `Thread.name` is read-only, no `threading.enumerate`
/`excepthook`/`settrace`, and thread exceptions print `kind: message` to stderr.
"""
from __future__ import annotations
from serpentine import Thread, Timer, dataclass, Mut, Ref, Owned, PyVal, Callable
from serp_threading_core import th_ident as _th_ident, th_name as _th_name
from serp_threading_core import th_active_count as _th_active_count, th_main_ident as _th_main_ident
from serp_threading_core import tls_set as _tls_set, tls_get as _tls_get
from serp_threading_core import tls_has as _tls_has, tls_del as _tls_del
from serp_threading_core import lock_new as _lock_new, lock_acquire as _lock_acquire
from serp_threading_core import lock_release as _lock_release, lock_locked as _lock_locked
from serp_threading_core import lock_owned as _lock_owned
from serp_threading_core import event_new as _event_new, event_set as _event_set
from serp_threading_core import event_clear as _event_clear, event_is_set as _event_is_set
from serp_threading_core import event_wait as _event_wait
from serp_threading_core import sem_new as _sem_new, sem_acquire as _sem_acquire
from serp_threading_core import sem_release as _sem_release, sem_value as _sem_value
from serp_threading_core import cond_new as _cond_new, cond_wait as _cond_wait
from serp_threading_core import cond_notify as _cond_notify
from serp_threading_core import barrier_new as _barrier_new, barrier_wait as _barrier_wait
from serp_threading_core import barrier_reset as _barrier_reset, barrier_abort as _barrier_abort
from serp_threading_core import barrier_parties as _barrier_parties
from serp_threading_core import barrier_n_waiting as _barrier_n_waiting
from serp_threading_core import barrier_broken as _barrier_broken

TIMEOUT_MAX: float = 4294967.0


class BrokenBarrierError(RuntimeError):
    pass


def _lock_timeout_ms(blocking: bool, timeout: float) -> int:
    """Translate Lock.acquire(blocking, timeout) into runtime milliseconds."""
    if not blocking:
        if timeout != -1.0:
            raise ValueError("can't specify a timeout for a non-blocking call")
        return 0
    if timeout == -1.0:
        return -1
    if timeout < 0.0:
        raise ValueError("timeout value must be a non-negative number")
    return int(timeout * 1000.0)


def _opt_timeout_ms(timeout: float | None) -> int:
    """Translate an optional seconds timeout into runtime milliseconds (-1 = forever)."""
    if timeout is None:
        return -1
    if timeout < 0.0:
        raise ValueError("timeout value must be a non-negative number")
    return int(timeout * 1000.0)


@dataclass
class Lock:
    _h: int

    def __init__(self: Mut[Lock]) -> None:
        self._h = _lock_new()

    def acquire(self: Ref[Lock], blocking: bool = True, timeout: float = -1.0) -> bool:
        """Acquire the lock; returns False only when non-blocking/timed out."""
        return _lock_acquire(self._h, _lock_timeout_ms(blocking, timeout), 0)

    def release(self: Ref[Lock]) -> None:
        """Release the lock (RuntimeError if it is not held)."""
        _lock_release(self._h, 0)

    def locked(self: Ref[Lock]) -> bool:
        """Whether the lock is currently held by any thread."""
        return _lock_locked(self._h)

    def __enter__(self: Ref[Lock]) -> Lock:
        _lock_acquire(self._h, -1, 0)
        return self

    def __exit__(self: Mut[Lock], exc_type: None, exc: None, tb: None) -> None:
        _lock_release(self._h, 0)


@dataclass
class RLock:
    _h: int

    def __init__(self: Mut[RLock]) -> None:
        self._h = _lock_new()

    def acquire(self: Ref[RLock], blocking: bool = True, timeout: float = -1.0) -> bool:
        """Acquire (re-entrantly for the owning thread)."""
        return _lock_acquire(self._h, _lock_timeout_ms(blocking, timeout), 1)

    def release(self: Ref[RLock]) -> None:
        """Release one level (RuntimeError if not owned by this thread)."""
        _lock_release(self._h, 1)

    def locked(self: Ref[RLock]) -> bool:
        """Whether the lock is held by any thread."""
        return _lock_locked(self._h)

    def _is_owned(self: Ref[RLock]) -> bool:
        """Whether the calling thread owns the lock."""
        return _lock_owned(self._h)

    def __enter__(self: Ref[RLock]) -> RLock:
        _lock_acquire(self._h, -1, 1)
        return self

    def __exit__(self: Mut[RLock], exc_type: None, exc: None, tb: None) -> None:
        _lock_release(self._h, 1)


@dataclass
class Event:
    _h: int

    def __init__(self: Mut[Event]) -> None:
        self._h = _event_new()

    def set(self: Ref[Event]) -> None:
        """Set the flag and wake all waiters."""
        _event_set(self._h)

    def clear(self: Ref[Event]) -> None:
        """Reset the flag."""
        _event_clear(self._h)

    def is_set(self: Ref[Event]) -> bool:
        """Whether the flag is set."""
        return _event_is_set(self._h)

    def wait(self: Ref[Event], timeout: float | None = None) -> bool:
        """Block until set (or timeout); returns the flag state."""
        return _event_wait(self._h, _opt_timeout_ms(timeout))


@dataclass
class Semaphore:
    _h: int

    def __init__(self: Mut[Semaphore], value: int = 1) -> None:
        if value < 0:
            raise ValueError("semaphore initial value must be >= 0")
        self._h = _sem_new(value)

    def acquire(self: Ref[Semaphore], blocking: bool = True, timeout: float | None = None) -> bool:
        """Decrement the counter, blocking while it is zero."""
        if not blocking:
            if timeout is not None:
                raise ValueError("can't specify timeout for non-blocking acquire")
            return _sem_acquire(self._h, 0)
        return _sem_acquire(self._h, _opt_timeout_ms(timeout))

    def release(self: Ref[Semaphore], n: int = 1) -> None:
        """Increment the counter by n."""
        _sem_release(self._h, n)

    def __enter__(self: Ref[Semaphore]) -> Semaphore:
        _sem_acquire(self._h, -1)
        return self

    def __exit__(self: Mut[Semaphore], exc_type: None, exc: None, tb: None) -> None:
        _sem_release(self._h, 1)


@dataclass
class BoundedSemaphore:
    _h: int
    _initial: int

    def __init__(self: Mut[BoundedSemaphore], value: int = 1) -> None:
        if value < 0:
            raise ValueError("semaphore initial value must be >= 0")
        self._h = _sem_new(value)
        self._initial = value

    def acquire(self: Ref[BoundedSemaphore], blocking: bool = True,
                timeout: float | None = None) -> bool:
        """Decrement the counter, blocking while it is zero."""
        if not blocking:
            if timeout is not None:
                raise ValueError("can't specify timeout for non-blocking acquire")
            return _sem_acquire(self._h, 0)
        return _sem_acquire(self._h, _opt_timeout_ms(timeout))

    def release(self: Ref[BoundedSemaphore], n: int = 1) -> None:
        """Increment the counter by n, refusing to exceed the initial value."""
        if _sem_value(self._h) + n > self._initial:
            raise ValueError("Semaphore released too many times")
        _sem_release(self._h, n)

    def __enter__(self: Ref[BoundedSemaphore]) -> BoundedSemaphore:
        _sem_acquire(self._h, -1)
        return self

    def __exit__(self: Mut[BoundedSemaphore], exc_type: None, exc: None, tb: None) -> None:
        self.release(1)


@dataclass
class Condition:
    _h: int
    _lock_h: int
    _reentrant: int

    def __init__(self: Mut[Condition], lock: Owned[Lock | RLock | None] = None) -> None:
        lock_h: int = 0
        reentrant: int = 1
        if lock is None:
            lock_h = _lock_new()
        elif isinstance(lock, Lock):
            lock_h = lock._h
            reentrant = 0
        elif isinstance(lock, RLock):
            lock_h = lock._h
        self._h = _cond_new()
        self._lock_h = lock_h
        self._reentrant = reentrant

    def acquire(self: Ref[Condition], blocking: bool = True, timeout: float = -1.0) -> bool:
        """Acquire the underlying lock."""
        return _lock_acquire(self._lock_h, _lock_timeout_ms(blocking, timeout), self._reentrant)

    def release(self: Ref[Condition]) -> None:
        """Release the underlying lock."""
        _lock_release(self._lock_h, self._reentrant)

    def wait(self: Ref[Condition], timeout: float | None = None) -> bool:
        """Release the lock, wait for notify (or timeout), reacquire; False on timeout."""
        if not _lock_owned(self._lock_h):
            raise RuntimeError("cannot wait on un-acquired lock")
        return _cond_wait(self._h, self._lock_h, _opt_timeout_ms(timeout))

    def wait_for(self: Ref[Condition], predicate: Callable[[], bool],
                 timeout: float | None = None) -> bool:
        """Wait until predicate() is true (re-checked after each notify); returns its last value."""
        result: bool = predicate()
        if timeout is None:
            while not result:
                self.wait(None)
                result = predicate()
            return result
        remaining: float = timeout
        while not result and remaining > 0.0:
            self.wait(remaining)
            result = predicate()
            remaining = remaining - 0.001
        return result

    def notify(self: Ref[Condition], n: int = 1) -> None:
        """Wake up to n waiters."""
        if not _lock_owned(self._lock_h):
            raise RuntimeError("cannot notify on un-acquired lock")
        _cond_notify(self._h, n)

    def notify_all(self: Ref[Condition]) -> None:
        """Wake every waiter."""
        if not _lock_owned(self._lock_h):
            raise RuntimeError("cannot notify on un-acquired lock")
        _cond_notify(self._h, 1000000000)

    def __enter__(self: Ref[Condition]) -> Condition:
        _lock_acquire(self._lock_h, -1, self._reentrant)
        return self

    def __exit__(self: Mut[Condition], exc_type: None, exc: None, tb: None) -> None:
        _lock_release(self._lock_h, self._reentrant)


@dataclass
class Barrier:
    _h: int
    _timeout_ms: int

    def __init__(self: Mut[Barrier], parties: int, timeout: float | None = None) -> None:
        self._h = _barrier_new(parties)
        self._timeout_ms = _opt_timeout_ms(timeout)

    def wait(self: Ref[Barrier], timeout: float | None = None) -> int:
        """Wait for all parties; returns this thread's arrival index."""
        ms: int = self._timeout_ms
        if timeout is not None:
            ms = _opt_timeout_ms(timeout)
        r: int = _barrier_wait(self._h, ms)
        if r < 0:
            raise BrokenBarrierError("")
        return r

    def reset(self: Ref[Barrier]) -> None:
        """Return the barrier to its initial state (waiters see BrokenBarrierError)."""
        _barrier_reset(self._h)

    def abort(self: Ref[Barrier]) -> None:
        """Break the barrier."""
        _barrier_abort(self._h)

    @property
    def parties(self: Ref[Barrier]) -> int:
        return _barrier_parties(self._h)

    @property
    def n_waiting(self: Ref[Barrier]) -> int:
        return _barrier_n_waiting(self._h)

    @property
    def broken(self: Ref[Barrier]) -> bool:
        return _barrier_broken(self._h)


@dataclass
class local:
    _tag: int

    def __init__(self: Mut[local]) -> None:
        self._tag = 0

    def set(self: Ref[local], name: str, value: PyVal) -> None:
        """Store a value visible only to the calling thread."""
        _tls_set(name, value)

    def get(self: Ref[local], name: str, default: PyVal = None) -> PyVal:
        """Read the calling thread's value (default when unset)."""
        if _tls_has(name):
            return _tls_get(name)
        return default

    def has(self: Ref[local], name: str) -> bool:
        """Whether the calling thread has set the name."""
        return _tls_has(name)

    def delete(self: Ref[local], name: str) -> None:
        """Remove the calling thread's value (AttributeError when unset)."""
        if not _tls_del(name):
            raise AttributeError(f"'_thread._local' object has no attribute '{name}'")


@dataclass
class _ThreadInfo:
    name: str
    ident: int
    daemon: bool

    def is_alive(self: Ref[_ThreadInfo]) -> bool:
        """The described thread is running (it is asking)."""
        return True


def current_thread() -> _ThreadInfo:
    """Describe the calling thread (name/ident/daemon)."""
    return _ThreadInfo(_th_name(), _th_ident(), _th_ident() != _th_main_ident())


def main_thread() -> _ThreadInfo:
    """Describe the main thread."""
    return _ThreadInfo("MainThread", _th_main_ident(), False)


def get_ident() -> int:
    """Identifier of the calling thread."""
    return _th_ident()


def get_native_id() -> int:
    """Identifier of the calling thread (same as get_ident here)."""
    return _th_ident()


def active_count() -> int:
    """Number of alive threads including the main thread."""
    return _th_active_count()
