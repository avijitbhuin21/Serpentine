"""serp-threading-core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_threading_core import ...` (rtlib.py); under
CPython these mirror the handle-based tables in prelude.rs (same state machines,
same error messages) on top of stdlib `threading`.
"""

import threading as _threading

__all__ = ["th_ident", "th_name", "th_active_count", "th_main_ident",
           "tls_set", "tls_get", "tls_has", "tls_del",
           "lock_new", "lock_acquire", "lock_release", "lock_locked", "lock_owned",
           "event_new", "event_set", "event_clear", "event_is_set", "event_wait",
           "sem_new", "sem_acquire", "sem_release", "sem_value",
           "cond_new", "cond_wait", "cond_notify",
           "barrier_new", "barrier_wait", "barrier_reset", "barrier_abort",
           "barrier_parties", "barrier_n_waiting", "barrier_broken"]

_MAIN_IDENT = _threading.main_thread().ident
_tls = _threading.local()


def th_ident():
    """Current thread identifier."""
    return _threading.get_ident()


def th_name():
    """Current thread name."""
    return _threading.current_thread().name


def th_active_count():
    """Number of alive threads including the main thread."""
    return _threading.active_count()


def th_main_ident():
    """Main thread identifier."""
    return _MAIN_IDENT


def _tls_map():
    """The calling thread's local key/value store."""
    m = getattr(_tls, "m", None)
    if m is None:
        m = {}
        _tls.m = m
    return m


def tls_set(key, val):
    """Store a thread-local value."""
    _tls_map()[key] = val


def tls_get(key):
    """Read a thread-local value (None when unset)."""
    return _tls_map().get(key)


def tls_has(key):
    """Whether a thread-local key exists."""
    return key in _tls_map()


def tls_del(key):
    """Remove a thread-local key; True when it existed."""
    return _tls_map().pop(key, _tls) is not _tls


def _timeout(ms):
    """Translate a millisecond timeout (-1 = forever) into seconds or None."""
    return None if ms < 0 else ms / 1000.0


class _LockRec:
    def __init__(self):
        self.cv = _threading.Condition(_threading.Lock())
        self.locked = False
        self.owner = 0
        self.count = 0


_LOCKS = []


def _get(table, h, what):
    """Resolve a 1-based handle."""
    if h < 1 or h > len(table):
        raise ValueError(f"invalid {what} handle")
    return table[h - 1]


def lock_new():
    """Create a lock; returns its handle."""
    _LOCKS.append(_LockRec())
    return len(_LOCKS)


def lock_acquire(h, timeout_ms, reentrant):
    """Acquire (blocking with timeout_ms, 0 = try, -1 = forever); True on success."""
    rec = _get(_LOCKS, h, "lock")
    me = th_ident()
    with rec.cv:
        if reentrant and rec.locked and rec.owner == me:
            rec.count += 1
            return True
        if rec.locked and timeout_ms == 0:
            return False
        if not rec.cv.wait_for(lambda: not rec.locked, _timeout(timeout_ms)):
            return False
        rec.locked = True
        rec.owner = me
        rec.count = 1
        return True


def lock_release(h, reentrant):
    """Release a lock (RuntimeError on unlocked / foreign release)."""
    rec = _get(_LOCKS, h, "lock")
    with rec.cv:
        if not rec.locked:
            raise RuntimeError("cannot release un-acquired lock" if reentrant
                               else "release unlocked lock")
        if reentrant and rec.owner != th_ident():
            raise RuntimeError("cannot release un-acquired lock")
        rec.count -= 1
        if rec.count <= 0:
            rec.locked = False
            rec.owner = 0
            rec.count = 0
            rec.cv.notify()


def lock_locked(h):
    """Whether the lock is currently held."""
    return _get(_LOCKS, h, "lock").locked


def lock_owned(h):
    """Whether the calling thread holds the lock."""
    rec = _get(_LOCKS, h, "lock")
    return rec.locked and rec.owner == th_ident()


def _release_save(rec):
    with rec.cv:
        if not rec.locked or rec.owner != th_ident():
            raise RuntimeError("cannot wait on un-acquired lock")
        saved = rec.count
        rec.locked = False
        rec.owner = 0
        rec.count = 0
        rec.cv.notify()
    return saved


def _acquire_restore(rec, count):
    with rec.cv:
        rec.cv.wait_for(lambda: not rec.locked)
        rec.locked = True
        rec.owner = th_ident()
        rec.count = max(count, 1)


_EVENTS = []


def event_new():
    """Create an event; returns its handle."""
    _EVENTS.append(_threading.Event())
    return len(_EVENTS)


def event_set(h):
    """Set the event."""
    _get(_EVENTS, h, "event").set()


def event_clear(h):
    """Clear the event."""
    _get(_EVENTS, h, "event").clear()


def event_is_set(h):
    """Whether the event is set."""
    return _get(_EVENTS, h, "event").is_set()


def event_wait(h, timeout_ms):
    """Wait for the event; True when set."""
    return _get(_EVENTS, h, "event").wait(_timeout(timeout_ms))


class _SemRec:
    def __init__(self, value):
        self.cv = _threading.Condition(_threading.Lock())
        self.value = value


_SEMS = []


def sem_new(value):
    """Create a counting semaphore."""
    if value < 0:
        raise ValueError("semaphore initial value must be >= 0")
    _SEMS.append(_SemRec(value))
    return len(_SEMS)


def sem_acquire(h, timeout_ms):
    """Acquire one unit; True on success."""
    rec = _get(_SEMS, h, "semaphore")
    with rec.cv:
        if rec.value <= 0 and timeout_ms == 0:
            return False
        if not rec.cv.wait_for(lambda: rec.value > 0, _timeout(timeout_ms)):
            return False
        rec.value -= 1
        return True


def sem_release(h, n):
    """Release n units."""
    if n < 1:
        raise ValueError("n must be one or more")
    rec = _get(_SEMS, h, "semaphore")
    with rec.cv:
        rec.value += n
        rec.cv.notify_all()


def sem_value(h):
    """Current semaphore count."""
    return _get(_SEMS, h, "semaphore").value


class _CondRec:
    def __init__(self):
        self.cv = _threading.Condition(_threading.Lock())
        self.waiting = 0
        self.tickets = 0


_CONDS = []


def cond_new():
    """Create a condition variable."""
    _CONDS.append(_CondRec())
    return len(_CONDS)


def cond_wait(h, lock_h, timeout_ms):
    """Release the lock, wait for a notify ticket, reacquire; False on timeout."""
    cond = _get(_CONDS, h, "condition")
    lock = _get(_LOCKS, lock_h, "lock")
    saved = _release_save(lock)
    with cond.cv:
        cond.waiting += 1
        if cond.tickets > 0:
            got = True
        elif timeout_ms == 0:
            got = False
        else:
            got = cond.cv.wait_for(lambda: cond.tickets > 0, _timeout(timeout_ms))
        if got:
            cond.tickets -= 1
        cond.waiting -= 1
    _acquire_restore(lock, saved)
    return got


def cond_notify(h, n):
    """Hand out up to n wake-up tickets."""
    cond = _get(_CONDS, h, "condition")
    with cond.cv:
        avail = max(cond.waiting - cond.tickets, 0)
        cond.tickets += min(n, avail)
        cond.cv.notify_all()


class _BarRec:
    def __init__(self, parties):
        self.cv = _threading.Condition(_threading.Lock())
        self.parties = parties
        self.count = 0
        self.generation = 0
        self.broken = False


_BARS = []


def barrier_new(parties):
    """Create a barrier for `parties` threads."""
    if parties < 1:
        raise ValueError("parties must be > 0")
    _BARS.append(_BarRec(parties))
    return len(_BARS)


def barrier_wait(h, timeout_ms):
    """Wait at the barrier: arrival index, -1 when broken, -2 on timeout (breaks it)."""
    rec = _get(_BARS, h, "barrier")
    with rec.cv:
        if rec.broken:
            return -1
        idx = rec.count
        rec.count += 1
        if rec.count == rec.parties:
            rec.count = 0
            rec.generation += 1
            rec.cv.notify_all()
            return idx
        gen = rec.generation
        ok = rec.cv.wait_for(lambda: rec.generation != gen or rec.broken, _timeout(timeout_ms))
        if not ok:
            rec.broken = True
            rec.cv.notify_all()
            return -2
        if rec.broken and rec.generation == gen:
            return -1
        return idx


def barrier_reset(h):
    """Reset the barrier (breaks it for current waiters)."""
    rec = _get(_BARS, h, "barrier")
    with rec.cv:
        if rec.count > 0:
            rec.broken = True
            rec.generation += 1
        else:
            rec.broken = False
        rec.count = 0
        rec.cv.notify_all()


def barrier_abort(h):
    """Put the barrier into the broken state."""
    rec = _get(_BARS, h, "barrier")
    with rec.cv:
        rec.broken = True
        rec.cv.notify_all()


def barrier_parties(h):
    """Number of parties."""
    return _get(_BARS, h, "barrier").parties


def barrier_n_waiting(h):
    """Threads currently waiting."""
    return _get(_BARS, h, "barrier").count


def barrier_broken(h):
    """Whether the barrier is broken."""
    return _get(_BARS, h, "barrier").broken
