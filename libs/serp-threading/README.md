# serp-threading

Drop-in replacement for CPython's `threading` module (D9 v2). `Thread` and
`Timer` are language intrinsics; the sync primitives are runtime-held handles
(`Mutex`/`Condvar` tables in the runtime, no crates). Under CPython the
`serp_threading_core` delegate mirrors the same state machines on stdlib
`threading`, so output is byte-identical across both worlds.

## API

- `Thread(target=f, args=(...), name=None, daemon=False)` → `.start()`,
  `.join(timeout=None)`, `.is_alive()`, `.name`, `.ident`, `.daemon`.
  `Timer(interval, function, args=())` adds `.cancel()`.
  The target is a **named module function** whose parameters are Send-by-copy:
  `int`/`float`/`bool`/`str`/`bytes`, or `Owned[C]` where `C` is a dataclass made
  only of those scalars (the sync primitives below qualify). Non-daemon threads are
  joined when `main()` returns, like CPython.
- `Lock`, `RLock` — `acquire(blocking=True, timeout=-1)`, `release()`, `locked()`, `with`.
- `Event` — `set/clear/is_set/wait(timeout=None)`.
- `Semaphore(value=1)`, `BoundedSemaphore(value=1)` — `acquire(blocking, timeout)`, `release(n=1)`, `with`.
- `Condition(lock=None)` — `acquire/release/wait(timeout)/wait_for(pred, timeout)/notify(n)/notify_all()`, `with`.
- `Barrier(parties, timeout=None)` — `wait(timeout)`, `reset()`, `abort()`, `parties`, `n_waiting`, `broken`; `BrokenBarrierError`.
- `local()` — thread-local store: `set(name, value)`, `get(name, default=None)`, `has(name)`, `delete(name)`.
- `current_thread()`, `main_thread()` (`.name`/`.ident`/`.daemon`), `get_ident()`, `get_native_id()`, `active_count()`, `TIMEOUT_MAX`.

## Divergences

No shared mutable objects cross the thread boundary — hand data over through
`serp_queue` (deep-copied PyVal items) or thread return values. `Thread` targets
must be module functions (no lambdas/bound methods, no `kwargs=`); `Thread.name`
is read-only; `local()` uses `get/set/has/delete` instead of attribute access;
uncaught thread exceptions print `Kind: message` to stderr; no `enumerate()`,
`excepthook`, `settrace`/`setprofile`, `stack_size`.

## Install

```
serp add serp-threading
pip install serp-threading
```
