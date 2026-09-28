"""Builtin value classes every Serpentine program can name without importing.

`slice` mirrors CPython's builtin: `x[a:b]` on a class with `__getitem__` reaches the
method as `slice(a, b, None)` natively, exactly the object CPython passes (D43).
"""
from __future__ import annotations
from serpentine import PyVal, dataclass


@dataclass
class slice:
    start: PyVal
    stop: PyVal
    step: PyVal
