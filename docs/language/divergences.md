# Divergences: native binary vs CPython

The Dual-Execution Guarantee promises identical behavior for every accepted program.
This page is the **complete** list of deliberate exceptions; anything else that differs
is a Serpentine bug. (Normative table: `../spec.md` §10; decisions: `../decisions.md`.)

## Backends and build modes: none

There are **no behavioral divergences between Backend A (Rust) and Backend B (direct
LLVM)**, and **none between `--debug` and release builds** of either backend — debug and
release differ only in compile time and optimization level. The full accept corpus runs
byte-identically through both backends (`tools/run_differential_tests.py`,
`tools/run_llvm_differential.py`); any difference between them is a bug.

## The one you must know

**Integers are 64-bit** and overflow **traps** with
`OverflowError: Serpentine int operation overflowed 64 bits` (never wraps). CPython has
arbitrary precision. If your program needs big ints, it is not a Serpentine program yet.

## Timing and identity

- **Destruction timing** — native frees values deterministically at scope end; CPython
  uses refcounting + GC. Unobservable unless you rely on destruction timing (`upgrade()`
  of a `Weak` can return `None` natively but never under CPython, where the shim keeps
  the referent alive).
- **No object identity** — `is` / `id()` are rejected (`SE207`) except `is None`.
- **Recursion depth** — CPython raises `RecursionError` around 1000 frames; native
  binaries use the real stack.

## Fixed in the implementation (must match, not documented away)

Floor division and modulo on negatives; container/f-string `repr`; shortest-roundtrip
float repr; insertion-ordered dicts; `ZeroDivisionError` for float ops (no IEEE inf
leak). These are runtime/codegen obligations covered by the differential suite.

## Output & errors

- **Unhandled runtime error** — same class, same message, exit status 1 on both sides.
  Native binaries print a `Traceback (most recent call last):` with the same `.py` file,
  line and function for every Serpentine frame (checked by `tools/run_traceback_check.py`).
  They omit CPython's `<module>` frame and source-line excerpts, and collapse repeated frames
  of the same function.
- **stdout line endings & encoding** — native always writes UTF-8 with `\n`; CPython uses
  OS text mode (`\r\n` and cp1252 pipes on Windows). The differential harness normalizes
  line endings and pins CPython to `PYTHONIOENCODING=utf-8`; on Linux/macOS the defaults
  already agree.
- **`sys.argv[0]`** — the native binary path vs the `.py` path.
- **`repr` of a `Weak` field** — `<weak>` natively; the CPython shim (identity wrappers)
  shows the referent.

## Tier-2 corners (Phase 4)

- **`chr()` of a lone surrogate** (0xD800–0xDFFF) raises `ValueError` natively; CPython
  constructs a lone-surrogate string. Surrogate *pairs* assembled from `\u` escapes (as
  in JSON parsing) behave identically.
- **`round(x, n)` with `n < 0`** rounds the binary value at a scaled position; CPython
  rounds the decimal digit string. Differences are confined to exact-tie corners of
  already-inexact doubles. (`n >= 0` and `round(x)` match CPython exactly, including
  ties-to-even.)
- **Huge JSON-style integer literals** parsed with `int(s)` overflow natively (see the
  64-bit rule) where CPython returns a big int.

## Safety limits (hardening, 2026-09-30)

These apply in **both** worlds (the CPython facades enforce the same caps) wherever CPython
itself would hang, exhaust memory or crash:

- **`serp-re`**: each match attempt may run at most `STEP_LIMIT` (1,000,000) VM steps and
  recurse at most `MAX_DEPTH` (10,000) levels. Catastrophic backtracking or very deep
  quantified matches raise `serp_re.error(...)` where CPython `re` would hang. The CPython
  facade can still hit `RecursionError` earlier (around 1,000 frames).
- **`serp-zlib` / `serp-zipfile`**: decompression output is capped at 256 MiB, raising
  `ValueError("decompressed data exceeds limit (256 MiB)")` (bomb guard).
- **`serp-http-server` / Venom**: request bodies over `MAX_BODY` (16 MiB) are refused with
  `413 Payload Too Large` before being read; request heads are capped at 64 KiB.
- **Stacks**: the program entry and every runtime-spawned thread run on a 256 MiB reserved
  stack (address space, committed lazily), so deep recursion behaves the same on Windows
  (1 MiB default) as on Linux/macOS.

## Policy

Every divergence must be **checker-rejected**, **fixed in the implementation**, or a
**loud documented decision** on this page. Never silent drift.
