# serp-queue

Drop-in replacement for CPython's `queue` module: thread-safe `Queue` and
`LifoQueue` whose items are dynamic values (PyVal: None/bool/int/float/str/bytes
and lists/dicts of those), deep-copied across the thread boundary. This is the
data channel for `serp-threading`. Native builds use a `Mutex`+`Condvar` table in
the runtime; under CPython the `serp_queue_core` delegate uses stdlib `queue`.

## API

- `Queue(maxsize=0)`, `LifoQueue(maxsize=0)`
- `put(item, block=True, timeout=None)`, `put_nowait(item)` — raise `Full`
- `get(block=True, timeout=None)`, `get_nowait()` — raise `Empty`
- `qsize()`, `empty()`, `full()`, `maxsize`
- `task_done()`, `join()`

Divergences: no `PriorityQueue`/`SimpleQueue`; items are copies, not shared
references; `qsize()` is exact.

## Install

```
serp add serp-queue
pip install serp-queue
```
