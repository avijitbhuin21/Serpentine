# Benchmarks — Phase 3 (§5.11)

> Measured 2026-07-17 on the development machine (Windows, x86_64), `tools/run_benchmarks.py`,
> median of 3 runs. serp = Backend A native binary (`serp build`, rustc `-C opt-level=2`).
> Outputs of every runner are byte-compared before timing counts.

## Comparison targets

| target | status |
|---|---|
| CPython 3.11 (venv) | measured |
| serp native (Backend A) | measured |
| handwritten Rust (`benchmarks/rust/`) | measured for fib + alloc |
| Codon | **not runnable — Codon has no Windows support.** The alloc-churn benchmark is designed as the Codon-differentiator (Boehm-GC pressure); run it on Linux/macOS when available. |
| mypyc | not runnable — requires MSVC `cl.exe`, absent from this host |

## Results

| benchmark | workload | CPython | serp | speedup | handwritten Rust |
|---|---|---:|---:|---:|---:|
| `bench_fib.py` | fib(32), recursion + int arithmetic (overflow-checked) | 0.727 s | 0.020 s | **36x** | 0.012 s |
| `bench_floats.py` | Leibniz π, 10M float iterations | 2.319 s | 0.016 s | **143x** | — |
| `bench_alloc.py` | 300k iterations × (20-elem list + dataclass object), all short-lived | 0.876 s | 0.100 s | **8.8x** | 0.110 s |
| `bench_strings.py` | 300k × f-string → split → join → upper | 0.255 s | 0.407 s | **0.6x** | — |

## Reading the numbers

- **Numeric milestone: met.** 36–143x over CPython is the Codon-class band (Codon reports
  10–100x+ on comparable numeric kernels). serp's fib carries CPython-parity overflow checks
  on every add — the gap to handwritten Rust (which would wrap/UB instead) is that check.
- **Allocation-heavy milestone: the no-GC dividend is real.** The churn benchmark runs at
  parity with handwritten idiomatic Rust (0.100 s vs 0.110 s) — every list and object is
  freed deterministically at scope end, no collector, no sweep. This is the workload where a
  Boehm-GC runtime (Codon) pays; the head-to-head vs Codon itself must wait for a
  Linux/macOS host.
- **Strings: honest gap (0.6x).** The transformation pipeline allocates twice per producing
  op (`String` result → `Rc<str>` copy), and CPython's C string library is extremely
  optimized. Known fixes for Phase 4: byte-length fast path for ASCII `len`, buffer-reusing
  in-place ops, small-string optimization or arena allocation in the Phase-3+ runtime.
  Note: `Rc<str>` still wins where the spec intended — O(1) string *copies* (assignment,
  argument passing, container storage).
- A general win found while benchmarking: `for i in range(n)` previously materialized the
  whole range as a `Vec`; it is now a lazy iterator (alloc benchmark improved 4.5x → 8.8x).

## Reproduce

```
python tools/run_benchmarks.py            # all four
python tools/run_benchmarks.py fib        # one
```
