# Serpentine — Current Feature State

> Living snapshot of what the language, compiler, and tooling support **today**.
> The normative definition is [spec.md](spec.md); resolved design questions are in
> [decisions.md](decisions.md); the library ecosystem is tracked in [libraries.md](libraries.md).

**As of:** v0.5+ (2026-07-22). Suites: 66/66 accept differential (both backends,
debug + release), 58/58 reject, 29/29 library dual-run, rustc-agreement 0 disagreements.

## Language

### Types & ownership
- Full-annotation static typing over the Tier-0/1/2 surface: `int` (int64 + overflow trap),
  `float`, `bool`, `str`, `bytes`, `bytearray`, `list[T]`, `dict[K, V]`, `tuple`, `Optional[T]`,
  `None`, file handles.
- `PyVal` boxed dynamic values (decisions.md D10): immutable refcounted Copy handle over
  None/bool/int/float/str/bytes/list/dict with indexing, truthiness, Python-semantics
  `==`/`!=`, `len`, iteration, `in`, explicit `int()/float()/str()/bool()/bytes()` extraction
  and `pyval_kind()`; scalars/lists/str-keyed dicts coerce into `PyVal` at annotated
  boundaries. Powers the json/tomllib/sqlite3/csv.DictReader drop-ins.
- Ownership discipline via shim annotations: `Owned[T]`, `Ref[T]` / `Mut[T]` (parameter-only
  borrows), explicit `move()` at call sites and rebinds, drop at end of lexical scope.
- One-level field-sensitive borrow checking (partial moves), place rules (no move-out-by-index),
  iterator-invalidation and loan-conflict detection (any number of `Ref` XOR one `Mut`).
- Returned borrows forbidden (SE209); flow-sensitive `Optional` narrowing via `is None`.
- `Shared[T]` / `Weak[T]` escape hatch (`Rc<RefCell>`; cycles leak per D3).
- Generics: `TypeVar` + `Generic[T]` classes, monomorphized by AST copy; structural
  protocols (`Protocol`) as TypeVar bounds.

### Statements & expressions
- Functions, `if`/`while`/`for`, `break`/`continue`, ternary chains, f-strings.
- `for` over lists/dicts/`range` (lazy)/`enumerate`/`zip`/`reversed`/str, and over **user
  iterator objects** (`__next__(self: Mut[C]) -> T` + shape-enforced `__iter__`; `next(obj)`
  works and StopIteration ends the loop); `with open(...)`
  and `with` on user objects (`__enter__`/`__exit__`).
- List/dict comprehensions (one `for` + one `if`, Copy/fresh elements).
- `try`/`except`/`finally` with the maybe-moved join (D1); user exception classes
  (`class E(Base): pass`); fatal runtime errors are catchable error values.
- First-class functions: `Callable[[...], R]`, lambdas capturing by value (Copy only,
  frozen after capture; loop-assigned captures refused for CPython late-binding parity).
- `sorted(key=lambda ...)`, `sort`/`reverse`, `min`/`max`/`sum`/`abs`, `round`/`ord`/`chr`,
  conversions, str index/slice (char-based).

### Classes (Tier 1)
- `@dataclass` and regular classes; `Ref`/`Mut` self (no `Owned` self); dataclass field
  defaults (literals plus empty `[]`/`{}` containers, fresh per construction); classes in
  containers; class forward refs via `from __future__ import annotations`.
- Operator overloading: arithmetic + matmul, ordering, `__neg__`, `__getitem__`/`__setitem__`/
  `__len__`; plus `__str__` (drives `str()`, `print`, f-strings), `__repr__` (backend
  override — containers, `!r`, KeyError messages), `__post_init__` (validation/normalization
  run after every construction; can raise), `@property`, `@staticmethod`.
- Call-site conveniences: keyword arguments, literal default params, int→float coercion at
  call args, negative-literal constants.

### Explicitly out of scope (any tier)
`eval`/`exec`, monkeypatching, metaclasses, dynamic attributes, runtime reflection, multiple
inheritance, `globals()` mutation. Threading is parked (D4/D9: scoped threads planned, Wave 6).

## Compiler & runtime
- **Backend B (default):** direct LLVM IR via llvmlite (`llvmgen.py` + `llvmbuild.py`) against
  the `rt.rs` runtime ABI; release builds run a rustc `--emit=metadata` oracle pass.
- **Backend A (`--backend rust`):** structured Rust codegen, kept forever as the
  rustc-as-oracle reference.
- No GC: refcounted `Rc<str>` strings, drop insertion, static native binaries (~136 KB fib).
- Runtime-error parity with CPython messages (exit 1); byte-identical dual-run corpus on
  Windows/Linux/macOS.
- Benchmarks ([guides/benchmarks.md](guides/benchmarks.md)): fib ~36x, floats ~143x vs CPython.

## Tooling
- `serp check` — ownership/type diagnostics (SE0xx ownership, SE2xx types/subset).
- `serp build` — native binary (LLVM debug/release); `serp llvm` JIT-runs.
- `serp new` / `init` / `run` / `add` / `remove` / `test` — project scaffolding, `serp.toml` +
  `serp.lock` with transitive dependency resolution ([guides/packages.md](guides/packages.md)).
- `serp lsp` — dependency-free stdio LSP (full-sync diagnostics).
- `serpentine-lang` + `serpentine-shim` on PyPI; prebuilt runtime dist; tag-push trusted
  publishing ([guides/publishing.md](guides/publishing.md)).

## Libraries
30 `serp-*` libraries in `libs/` (Waves 1–4 shipped) — json, math, random, os, datetime,
pathlib, io, zipfile, sqlite, socket, url, http-server, fang (httpx façade with native TLS),
and more. Many are true CPython stdlib **drop-ins** (facade + `_core` rtlib pattern) —
including, since the PyVal push, `json`, `tomllib`, `sqlite3`, and `csv.DictReader`;
per-library drop-in status lives in [language/python-equivalence.md](language/python-equivalence.md)
and the tracker in [libraries.md](libraries.md).
