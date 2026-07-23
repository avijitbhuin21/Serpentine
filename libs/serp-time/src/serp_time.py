"""serp-time CPython delegate: native builds use runtime primitives instead.

The Serpentine compiler intercepts `from serp_time import ...` (rtlib.py) and
never reads this file; under CPython it re-exports the stdlib time members.
"""

from time import (time, monotonic, sleep, time_ns, monotonic_ns,
                  perf_counter, perf_counter_ns)

__all__ = ["time", "monotonic", "sleep", "time_ns", "monotonic_ns",
           "perf_counter", "perf_counter_ns"]
