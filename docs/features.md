# Serpentine — Current Feature State

> Living snapshot of what the language, compiler, and tooling support **today**.
> The normative definition is [spec.md](spec.md); resolved design questions are in
> [DECISIONS.md](DECISIONS.md); the library ecosystem is tracked in [libraries.md](libraries.md);
> production readiness in [readiness.md](readiness.md).

**As of:** v0.7.2 + `master` (2026-10-05). Suites: 106/106 accept differential (CPython vs
both backends, 3 OSes), 102/102 reject with exact SE codes, 70 library dual-run tests over 37
libs, rustc agreement 0 disagreements ([guides/testing.md](guides/testing.md)).

## Language

### Types & ownership
- Full-annotation static typing over the Tier-0/1/2 surface: `int` (int64 + overflow trap),
  `float`, `bool`, `str`, `bytes`, `bytearray`, `list[T]`, `dict[K, V]`, `set[T]`, `tuple`,
  `Optional[T]`, `None`, file handles.
- General unions (D24): `int | str` / `Union[A, B]` as closed runtime-tagged sums, narrowed
  with `isinstance()`; members must differ in runtime kind, and a member widens into the
  union implicitly at annotated boundaries.
- C-like enums (D21): `class C(Enum | IntEnum | StrEnum)` with constant `int`/`str` members,
  `C.MEMBER`, `.value`, `.name`, `C(value)` lookup and `==`/`!=`; a Copy scalar usable as a
  dict key, set element or field type.
- `PyVal` boxed dynamic values (decisions.md D10): immutable refcounted Copy handle over
  None/bool/int/float/str/bytes/list/dict with indexing, truthiness, Python-semantics
  `==`/`!=`, `len`, iteration, `in`, explicit `int()/float()/str()/bool()/bytes()` extraction,
  `pyval_kind()` and `pyval_json(v, ensure_ascii, compact)` (native JSON serialization —
  16.7x faster than the pure-Serpentine walk; backs `serp_json.dumps`);
  scalars/lists/str-keyed dicts coerce into `PyVal` at annotated
  boundaries. Powers the json/tomllib/sqlite3/csv.DictReader drop-ins.
- Ownership discipline via shim annotations: `Owned[T]`, `Ref[T]` / `Mut[T]` (parameter-only
  borrows), explicit `move()` at call sites and rebinds, drop at end of lexical scope.
- One-level field-sensitive borrow checking (partial moves), place rules (no move-out-by-index),
  iterator-invalidation and loan-conflict detection (any number of `Ref` XOR one `Mut`).
- Returned borrows forbidden (SE209); flow-sensitive `Optional` narrowing via `is None` and
  union narrowing via `isinstance()`.
- `Shared[T]` / `Weak[T]` escape hatch (`Rc<RefCell>`; cycles leak per D3).
- Generics: `TypeVar` + `Generic[T]` classes, monomorphized by AST copy; structural
  protocols (`Protocol`) as TypeVar bounds. A generic class may also inherit one
  non-generic base (`class Page(Envelope, Generic[T])`, D23); inheriting *from* a generic
  class is rejected. Its `@classmethod`s are called on an explicit instantiation —
  `Page[int].model_validate(d)` — where `cls`/`Self` mean `Page[int]` (D25).

### Statements & expressions
- Functions, `if`/`while`/`for`, `break`/`continue`, ternary chains, f-strings.
- `for` over lists/dicts/`range` (lazy)/`enumerate`/`zip`/`reversed`/str, and over **user
  iterator objects** (`__next__(self: Mut[C]) -> T` + shape-enforced `__iter__`; `next(obj)`
  works and StopIteration ends the loop); `with open(...)`
  and `with` on user objects (`__enter__`/`__exit__`).
- List/dict comprehensions (one `for` + one `if`, Copy/fresh elements).
- `try`/`except`/`finally` with the maybe-moved join (D1); user exception classes
  (`class E(Base): pass`); fatal runtime errors are catchable error values.
- First-class functions: `Callable[[...], R]` with **any param/return types** (non-Copy
  arguments require an explicit `move()` at the call site); lambdas capturing by value
  (Copy only, frozen after capture; loop-assigned captures refused for CPython
  late-binding parity).
- Registration-style decorators on module functions (`@deco`, `@deco(args)`; D13 —
  decorated name stays bound to the original, decorator result typechecked against the
  exact signature, applications run at startup in import order).
- `async def` / `await` on a baton-scheduled task runtime (D14 → D45): `await f(...)` runs the
  coroutine inline; `asyncio.create_task`/`gather`/`Task[T]`/`await task`/`done()` and
  `asyncio.sleep` suspend the current task with CPython's event-loop ordering; `async with`;
  every direct async call must be awaited or wrapped; `serp-asyncio` adds
  `Event`/`Lock`/`Semaphore`/`BoundedSemaphore`/`Queue`; sockets have an async mode that
  parks the task on the reactor instead of blocking (Fang `AsyncClient`, Venom `serve_conn`).
- Threads (D9 v1): `from serpentine import spawn`; `spawn(f, args...) -> JoinHandle[R]`,
  `.join()` returns the result or re-raises; arguments/returns are Send-by-copy
  (int/float/bool/str/bytes, SE216 otherwise); `Shared` cannot cross threads.
- `sorted(key=lambda ...)`, `sort`/`reverse`, `min`/`max`/`sum`/`abs`, `round`/`ord`/`chr`,
  conversions, str index/slice (char-based).

### Classes (Tier 1)
- `@dataclass` and regular classes; `Ref`/`Mut` self (no `Owned` self); dataclass field
  defaults (literals plus empty `[]`/`{}` containers, fresh per construction); classes in
  containers; class forward refs via `from __future__ import annotations`.
- **Single inheritance** (D15): `class Sub(Base)` flattens the base's fields and
  non-overridden methods into the subclass at check time (mixin semantics — no subtyping,
  no `super()`, no virtual dispatch; overriding replaces; field-less base classes allowed;
  `@classmethod`s and `@staticmethod`s are inherited too).
  Powers the serp-test `TestCase` model with build-time discovery in `serp test`.
- Operator overloading: arithmetic + matmul, ordering (a class's `__lt__`/`__gt__`/… may
  return **any type**, e.g. a boolean-mask object — D38), user `__eq__`/`__ne__` overloads and
  reflected `__radd__`/`__rsub__`/`__rmul__`/`__rtruediv__`/… (`2 * obj`, D39), bitwise `&`/`|`/`^` via
  `__and__`/`__or__`/`__xor__` and `~` via `__invert__` (class operands only), `__neg__`,
  `__getitem__`/`__setitem__`/`__len__`; **`@overload`-typed `__getitem__`** (D40 — the call
  site takes the matching stub's return type, so one indexer can yield a `Series` for a
  string key and a `DataFrame` for a mask); operator and `__getitem__` results are fresh owned
  values (assignable, attribute-addressable); plus `__str__` (drives `str()`, `print`, f-strings), `__repr__` (backend
  override — containers, `!r`, KeyError messages), `__post_init__` (validation/normalization
  run after every construction; can raise), `__init__` (a user constructor whose parameter
  list is independent of the field list; every field assigned exactly once — D22),
  `@property`, `@staticmethod`,
  `@classmethod` (D16 — `cls` is a build-time binding: `cls(...)`, `cls.other()`, `Self`
  returns).
- **Build-time field-table intrinsics** (D16): `fields_of(obj)`, `fields_json(cls)`,
  `fields_build(cls, d)` from `serpentine`, lowered to generated per-class functions —
  reflection-free model dumping/validation (powers serp-molt). `Annotated[T, ...]` extras
  and a `Field(...)` call in field-default position are kept as build-time field metadata,
  including `default_factory`.
- Call-site conveniences: keyword arguments, literal default params, int→float coercion at
  call args, negative-literal constants.

### Explicitly out of scope (any tier)
`eval`/`exec`, monkeypatching, metaclasses, dynamic attributes, runtime reflection,
subtype polymorphism (inheritance is compile-time flattening, D15), multiple inheritance,
`globals()` mutation.
Concurrency shipped as D9-v1 `spawn`/`join`; scoped borrows across threads and `Sync[T]`
remain future work.

## Compiler & runtime
- **Backend B (default):** direct LLVM IR via llvmlite (`llvmgen.py` + `llvmbuild.py`) against
  the `rt.rs` runtime ABI; release builds run a rustc `--emit=metadata` oracle pass.
- **Backend A (`--backend rust`):** structured Rust codegen, kept forever as the
  rustc-as-oracle reference.
- No GC: refcounted `Rc<str>` strings, drop insertion, static native binaries (~136 KB fib).
- Runtime-error parity with CPython messages (exit 1), plus a CPython-style traceback
  (`.py` file, line, function per frame) recorded on the error path only; byte-identical
  dual-run corpus on Windows/Linux/macOS.
- Every program and runtime thread runs on a 256 MiB reserved stack, so recursion depth is
  the same on every OS. Linux/macOS binaries ignore SIGPIPE.
- Safety limits in the bundled libs: regex step/depth caps (ReDoS), a 256 MiB decompression
  cap, a 16 MiB HTTP body cap (413) ([language/divergences.md](language/divergences.md)).
- Benchmarks ([guides/benchmarks.md](guides/benchmarks.md)): fib ~36x, floats ~143x vs CPython.

## Tooling
- `serp check` — ownership/type diagnostics (SE0xx ownership, SE2xx types/subset).
- `serp build` — native binary (LLVM debug/release); `serp llvm` JIT-runs.
- `serp new` / `init` / `run` / `add` / `remove` / `test` — project scaffolding, `serp.toml` +
  `serp.lock` with transitive dependency resolution ([guides/packages.md](guides/packages.md)).
- `serp lsp` — dependency-free stdio LSP (full-sync diagnostics).
- `serpentine-lang` + `serpentine-shim` on PyPI; prebuilt runtime dist; tag-push trusted
  publishing ([guides/publishing.md](guides/publishing.md)).
- Verification tooling: differential corpora, parser and compiler fuzzers, Miri/ASan runs,
  traceback/TLS checks and a soak test ([guides/testing.md](guides/testing.md)).

## Libraries
37 `serp-*` libraries in `libs/`, all on PyPI (Waves 1–6): stdlib drop-ins (json, re, csv,
datetime, pathlib, io, zipfile, sqlite3, socket, subprocess, threading, queue, asyncio, logging,
argparse, …) plus flagships **Molt** (pydantic), **Venom** (FastAPI), **Fang** (httpx with native
TLS), **Coil** (numpy) and **Scales** (pandas). Most are true CPython **drop-ins** (facade +
`_core` rtlib pattern). Per-library status and blockers live in the tracker,
[libraries.md](libraries.md).
