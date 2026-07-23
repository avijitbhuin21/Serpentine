# serp-time

Serpentine's time library ([R] runtime-backed) — stdlib-named surface.

- `from serp_time import time, monotonic, sleep, time_ns, monotonic_ns, perf_counter, perf_counter_ns`
- `time()` / `time_ns()` — seconds (float) / nanoseconds (int) since the Unix epoch.
- `monotonic()` / `monotonic_ns()` — monotonically non-decreasing; only differences are
  meaningful, and the reference point differs between CPython and native builds.
- `perf_counter()` / `perf_counter_ns()` — high-resolution counter (aliases the
  monotonic clock natively).
- `sleep(secs)` — blocks; `ValueError` on negative input.

Install into a Serpentine project with `serp add serp-time`.
