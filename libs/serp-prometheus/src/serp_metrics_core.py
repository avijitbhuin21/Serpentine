"""serp-metrics core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_metrics_core import ...` (rtlib.py); natively the
values live in a process-global, mutex-guarded map in the runtime (shared by every
thread). This file keeps the same contract over dicts guarded by a lock.

mx_add/mx_set/mx_get: float samples by key (missing keys read as 0.0).
mx_meta_set/mx_meta_get: string metadata by key (missing keys read as "").
mx_meta_add: append an item to a newline-separated list unless already present;
returns True when it was added.
"""

import threading as _threading

__all__ = ["mx_add", "mx_set", "mx_get", "mx_meta_set", "mx_meta_get", "mx_meta_add"]

_lock = _threading.Lock()
_vals: dict[str, float] = {}
_meta: dict[str, str] = {}


def mx_add(key: str, delta: float) -> None:
    """Add delta to a sample (creating it at 0.0)."""
    with _lock:
        _vals[key] = _vals.get(key, 0.0) + float(delta)


def mx_set(key: str, v: float) -> None:
    """Set a sample."""
    with _lock:
        _vals[key] = float(v)


def mx_get(key: str) -> float:
    """Read a sample (0.0 when absent)."""
    with _lock:
        return _vals.get(key, 0.0)


def mx_meta_set(key: str, v: str) -> None:
    """Set a metadata string."""
    with _lock:
        _meta[key] = v


def mx_meta_get(key: str) -> str:
    """Read a metadata string ("" when absent)."""
    with _lock:
        return _meta.get(key, "")


def mx_meta_add(key: str, item: str) -> bool:
    """Append item to a newline-separated metadata list unless present."""
    with _lock:
        cur = _meta.get(key, "")
        if cur and item in cur[1:].split("\n"):
            return False
        _meta[key] = cur + "\n" + item
        return True
