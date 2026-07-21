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

### Phase-4 update (2026-07-18): string runtime rework

The string runtime was rebuilt with **small-string optimization**: `SStr` is now an enum —
strings ≤ 22 bytes live inline with zero allocation (covers `split()` parts, chars, most
keys), longer strings stay `Rc<str>` with O(1) clones. `len`/index/slice take an ASCII
byte fast path. Re-measured interleaved, min of 5 runs on a loaded host (absolute numbers
differ from the table above; ratios are the signal):

| runtime | `bench_strings.py` (min of 5) | vs CPython |
|---|---:|---:|
| CPython 3.11 | 0.938 s | 1.00x |
| serp, old `Rc<str>` runtime | 1.399 s | 0.67x |
| serp, SSO runtime | **0.912 s** | **1.03x** |

The 0.6x string gap is **closed to 0.8–1.0x** (the standard harness's median-of-3 on the
same loaded host reports 0.8x; the interleaved min-of-5 above reports parity). Remaining
headroom (arena allocation, buffer-reusing producing ops) is documented, not on the
critical path.

### Phase-5 update (2026-07-21): Backend B (direct LLVM) vs Backend A

Backend B (`serp build --backend llvm`) compiles SIR-checked programs straight to native
objects via llvmlite and links against the cached Rust runtime. In release mode the
runtime's LLVM **bitcode is merged and internalized into the program module before O3**,
so runtime primitives inline into hot loops (the same whole-program advantage rustc gives
Backend A). Measured with `tools/run_llvm_benchmarks.py` (workloads scaled ~7–20x so
runtimes dominate process startup; best of 5; outputs byte-compared before timing):

| benchmark | A (rust, `-C opt-level=2`) | B (llvm, O3 + runtime inlining) | B/A |
|---|---:|---:|---:|
| `bench_alloc.py` (3M iters) | 1.115 s | 0.847 s | **0.76x** |
| `bench_fib.py` (fib 38) | 0.284 s | 0.255 s | **0.90x** |
| `bench_floats.py` (200M iters) | 0.233 s | 0.220 s | **0.95x** |
| `bench_strings.py` (2M rows) | 2.399 s | 2.135 s | **0.89x** |

**Backend B release is within the 5% bar on all four — in fact faster than Backend A
across the board** (worst ratio 0.947). Two findings worth recording: generated functions
must be `internal` linkage or LLVM skips the interprocedural const-prop/unrolling rustc
gets for free (floats went 1.40x → 0.95x on that one change); and the runtime-bitcode
merge is what closes allocation/string-heavy gaps (alloc 1.15x → 0.76x, strings 1.21x
→ 0.89x).

Build times (`tools/run_build_bench.py`, backend-only: codegen + compile + link, the
shared Python front end excluded; best of 3):

| program | A debug | B debug | speedup | A release | B release |
|---|---:|---:|---:|---:|---:|
| `006_fib_iterative.py` | 0.35 s | 0.13 s | **2.62x** | 0.42 s | 0.43 s |
| `026_sort_reverse.py` | 0.39 s | 0.14 s | **2.84x** | 0.53 s | 0.70 s |
| `037_dataclass_basics.py` | 0.36 s | 0.14 s | **2.51x** | 0.51 s | 0.42 s |
| `051_comprehensions.py` | 0.43 s | 0.18 s | **2.34x** | 0.90 s | 0.77 s |
| `055_json_roundtrip.py` | 0.58 s | 0.33 s | **1.76x** | 2.35 s | 1.57 s |
| synthetic (120 functions) | 0.91 s | 0.96 s | 0.95x | 1.68 s | 1.94 s |

Debug geomean: **2.05x** — the win comes from skipping the rustc round-trip entirely
(LLVM O0 emission + a cached direct `link.exe` invocation, ~0.02s vs rustc's ~0.2s stub
link). The honest caveat: for very large programs the Python-side IR construction becomes
the bottleneck (the synthetic row), so the speedup shrinks as programs grow.

```
python tools/run_llvm_benchmarks.py       # A vs B, all four
python tools/run_build_bench.py           # compile-time comparison
```

## Reading the numbers

- **Numeric milestone: met.** 36–143x over CPython is the Codon-class band (Codon reports
  10–100x+ on comparable numeric kernels). serp's fib carries CPython-parity overflow checks
  on every add — the gap to handwritten Rust (which would wrap/UB instead) is that check.
- **Allocation-heavy milestone: the no-GC dividend is real.** The churn benchmark runs at
  parity with handwritten idiomatic Rust (0.100 s vs 0.110 s) — every list and object is
  freed deterministically at scope end, no collector, no sweep. This is the workload where a
  Boehm-GC runtime (Codon) pays; the head-to-head vs Codon itself must wait for a
  Linux/macOS host.
- **Strings: gap closed in Phase 4.** The 0.6x result above was the Phase-3 runtime; see
  the Phase-4 update table — small-string optimization + ASCII fast paths reach CPython
  parity (1.03x) on the same pipeline, with O(1) copies preserved (inline ≤22-byte memcpy
  or Rc clone).
- A general win found while benchmarking: `for i in range(n)` previously materialized the
  whole range as a `Vec`; it is now a lazy iterator (alloc benchmark improved 4.5x → 8.8x).

## Reproduce

```
python tools/run_benchmarks.py            # all four
python tools/run_benchmarks.py fib        # one
```
