# Serpentine — Design Decisions

> Resolutions of the open questions in archive/research.md §8, decided in Phase 0. Reopening one of
> these is a spec change.

## D1 — Exceptions × ownership (§8.1)

**Decision:** `try` body is a lexical sub-scope; all borrows created inside it die at
`except`/`finally` entry as well as at normal exit. At `except` entry every place is in the
join of its states over all raising points (maybe-moved ⇒ unusable, `SE001`). Unwinding drops
owned values along the unwind path using per-place drop flags. Runtime errors are error values
from day one so Tier-1 can make them catchable.
**Rationale & prototype:** `language/exceptions-ownership.md`.

## D2 — Returned borrows (§8.3)

**Decision:** **Forbidden in Tier 0** (`SE209 returned-borrow`); return values are always
owned. Tier 1 may add Rust-style elision (single borrowed parameter ⇒ derivable lifetime) if
corpus data demands it.
**Rationale:** call-scoped borrows with no named lifetimes are the single biggest complexity
cut vs Rust; returned borrows would reintroduce lifetime reasoning immediately.

## D3 — `Shared[T]` cycles (§8.2)

**Decision:** Rust's answer — `Shared[T]` is plain refcounting (`Rc<T>`), cycles **leak**, and
`Weak[T]` is provided for back-edges. No static cycle-freedom analysis.
**Rationale:** ownership-DAG type systems that statically forbid cycles are a research project
on their own; leak-on-cycle is well-understood, documented, and matches the escape-hatch role
of `Shared`. The no-GC claim is unaffected (leaks ≠ collector).

## D4 — Threading posture (§8.4)

**Decision:** **Parked until Phase 3+.** Tier 0/1/2 are single-threaded; no `threading` import
(it's a bin-3 foreign import, `SE213`), no atomics in the runtime, `Rc` (not `Arc`) for
`str`/`Shared`. The ownership model is expected to yield `Send`/`Sync`-like rules nearly for
free when a no-GIL native mode is designed, but nothing in Tier 0–2 may presuppose it.
**Rationale:** archive/research.md §8.4's own proposal; threading before the checker is real would
multiply every design question.

## D5 — Compiler self-hosting (§8.5)

**Decision:** Kept as a **north-star, not a commitment.** The compiler is written in ordinary
Python (archive/research.md §4); no Tier decisions are made for self-hosting's sake.

## D6 — CPython interop boundary (§5.12, Phase 4)

**Decision:** **v0.1 refuses foreign imports** (`SE213` names the policy and points to
`guides/interop.md`). The deep-copy boundary (embed libpython, snapshot values both ways,
Tier-0 data only, no retained references, no callbacks) is fully specified in that document
and is the committed design if demand arrives; curated native reimplementation of specific
stdlib modules is the preferred pressure valve before that. Rationale: the zero-libpython
static binary is the Phase-3 headline product; dual execution already provides the ecosystem
during development; deep-copy is the only ownership-sound transfer and that part is settled
now so a later implementation cannot warp the model.

## D7 — User-defined iterators (Tier-2 scoping, Phase 4)

**Decision:** Tier 2 ships **built-in iterator forms only**: lazy `range`, dict views,
`enumerate`, and the Phase-4 additions `zip(a, b)`, `reversed(xs)`, and `for ch in s:`
(str iteration), plus comprehensions over all of them. User-defined `__iter__`/`__next__`
objects are **deferred**: a user iterator is a *stored borrow* of its container, which
Tier 0–2 forbid by design (no `Ref` fields, D2); doing this soundly requires the named-borrow
/ region machinery, and the corpus study recorded zero demand. Reopening this is a spec
change tied to the "iterators as first-class borrows" backlog item.

---

## Phase-4 incidental decisions (recorded for transparency)

- **Tier-2 surface (spec.md §14):** str indexing/slicing (`s[i]`, `s[a:b]`, no step),
  list/dict comprehensions (one `for`, one optional `if`), `sorted(xs)` and
  `sorted(xs, key=lambda v: ...)` (Copy elements; key returns int/float/str), `with
  open(...) as f:` (RAII sugar; the target scopes to the block and cannot be moved out),
  literal default parameter values, `zip`/`reversed`/str iteration, `round`/`ord`/`chr`,
  and structural protocols as generic bounds (`class P(Protocol)` + `TypeVar("T", bound=P)`,
  new code `SE215 unsatisfied-protocol`).
- **Comprehensions borrow their iterable** for the whole expression (SIR loans); the
  element expression must produce Copy or freshly-constructed values (`SE003` otherwise).
- **Key lambdas are the only closures in Tier 2**: exactly one parameter, expression body,
  may read enclosing locals, may not mutate or move anything it can reach (`SE004`/`SE005`).
- **`chr()` of a lone surrogate** raises `ValueError` natively (CPython constructs a lone
  surrogate string) — documented divergence; `round(x, n)` with `n < 0` uses scaled
  binary rounding (CPython rounds the decimal string) — divergence only in far corners.
- **`with` target names must be fresh** (no shadowing) and the name is *unknown* after the
  block — this keeps "file closed at block end" true on both sides of the dual-execution
  guarantee (CPython would allow touching the closed file object; Serpentine rejects it).

## D8 — Phase-5 LLVM backend runtime strategy (2026-07-21)

**Decision:** the Backend-B runtime is **`prelude.rs` compiled once behind a C ABI**, not a
hand-written C runtime. A thin wrapper file (`rt.rs`, ~60 `extern "C"` symbols) is
concatenated with `prelude.rs` and built ONCE per (source hash, rustc version, platform)
into a cached library under `%LOCALAPPDATA%/serp/rt/<key>/` (Unix: `~/.cache/serp/rt`;
`SERP_RT_CACHE` overrides; falls back to the system temp dir when the per-user dir is
virtualized). Everything is reused: SStr/SSO, shortest-roundtrip float repr, CPython error
messages, file IO — so repr/message parity is inherited, not re-implemented.

**ABI shape:** values cross the boundary as raw blobs — `SStr` is an opaque 24-byte blob,
lists/dicts are `{ptr, len, cap}` raw buffers with the element size passed per call (a dict
is a scan-based insertion-ordered list of key/value pairs, same as Backend A's `SerpDict`).
All type-directed logic (clone/drop/eq/ord/repr, dict scans, list element access, Shared
refcount+borrow-flag manipulation) is EMITTED as LLVM IR per type; the runtime stays
monomorphic and panic-free. Errors are error values: the runtime sets a pending
`SerpErr` and returns a status byte; generated functions return `{i1 err, T}` and branch to
per-function cleanup blocks (drop flags), giving unwind-path drops without landing pads.

**Linking (platform split):** on Windows the runtime is an **rlib** and the final link
compiles a 3-line Rust stub (`fn main` → `serp_entry()`) with `--extern serp_rt` plus the
LLVM object as a link-arg — rustc handles MSVC linker/CRT discovery, and MSVC `link.exe`
resolves archive symbols order-independently. On Unix the runtime is a **staticlib**, the
LLVM module defines `main` itself, and the link is `cc prog.o libserp_rt.a
<native-static-libs>` (the flag list is captured from rustc at runtime-build time). This
deviates from the checklist's literal "staticlib everywhere" on Windows to avoid duplicate
Rust-std symbols in a stub link; the "compile the runtime once, cache it, link objects
against it" contract is unchanged.

**Modes:** debug = opt 0, no pass pipeline; release = opt 3 + LLVM new-pass-manager O3
**with runtime-bitcode LTO**: the cached runtime is also emitted as LLVM bitcode
(`serp_rt.bc`, single CGU), merged into the program module, internalized, and optimized
together — runtime primitives inline into hot loops, and the final link then omits the
runtime library entirely (the object is runtime-complete; rustc's merge-functions aliases
would otherwise produce duplicate symbols). Generated functions carry `internal` linkage so
LLVM performs the same whole-program const-prop/inlining rustc gives Backend A. Identical
program behavior in both modes (divergence list gets a "none" entry). `serp llvm`
AOT-builds to a temp binary and runs it (the numeric-core MCJIT path is retired — one code
path, and Windows MCJIT required ELF hacks). Backend A remains the default `serp build`
backend and the rustc-as-oracle reference.

**Known bounded leaks (invisible to program semantics, recorded for honesty):** caught
exception values propagated across `try` re-raise clones may leak their message strings, and
temporaries leak on error edges (borrow flags are still released). Files, lists, dicts,
strings, and Shared boxes are dropped deterministically — Shared strong/weak counts are
exact (weak-upgrade observability), and drop-closes-file semantics are preserved.

## D9 — Concurrency posture (Phase-7 prerequisite decision, 2026-07-22)

**Decision:** Serpentine adopts **Rust's model: scoped threads + Send-checked captures**,
to be implemented in Wave 6 (nothing before it may presuppose threads). Concretely:

- The threading primitive is a **scoped spawn** (Rust `std::thread::scope` semantics):
  child threads may borrow stack data because the scope joins all children before it
  returns — no `'static` bound, no detached threads in v1.
- The checker gains **`Send` classification** derived from the existing ownership model:
  a type is Send unless it (transitively) contains `Shared[T]`/`Weak[T]` (which stay
  `Rc`-based and single-threaded, per D3/D8) or another non-Send type. Captures of a
  spawned closure are checked exactly like call-site conventions today: `Ref` captures
  require no `Mut` loan overlap across threads, `Mut`/`Owned` captures are exclusive —
  the aliasing XOR mutation rule already gives data-race freedom; Send-checking is the
  only new judgment.
- **Thread-safe sharing arrives as a separate type** (`Sync[T]`, `Arc<Mutex<T>>`-backed)
  when Wave 6 lands; `Shared[T]` is never silently upgraded to atomic refcounting (the
  single-threaded refcount fast path is a measured performance win, D8).
- **D4 stands until Wave 6 starts**: the runtime keeps `Rc`, no atomics, `threading`
  remains a refused bin-3 import (SE213).

**Rationale:** the borrow checker already proves the hard half (no aliased mutation);
Rust demonstrates that scoped threads + Send auditing is the smallest sound extension of
exactly this model, and it composes with everything shipped (error values, drops, the C
ABI runtime). Deciding this now unblocks Wave-4 server design (blocking/threaded model)
without committing any Tier 0–2 semantics.

## Phase-4 backlog decisions (2026-07-18)

- **Named element borrows are lexically block-scoped** (not NLL): `first = rows[0]` freezes
  `rows` until the end of the enclosing block, and `first` is unknown afterwards. Stricter
  than rustc (policy-only difference) but keeps the CPython alias unobservable: neither
  alias can be mutated while both exist. Ref-only (no `Mut` element borrows in v1).
- **`iter()`/`next()` ride the same block-region machinery.** Copy elements only (`next`
  copies out); `StopIteration` joins the known exception classes. `for` over an iterator
  handle stays rejected — `for` loops already borrow directly.
- **Owned self call syntax is `move(x).method()`** — the move is spelled at the receiver,
  reusing J3's explicit-transfer rule; no new syntax.
- **Field narrowing never applies through `Shared`** — runtime-shared aliases could
  invalidate the narrow between test and use.
- **String runtime = SSO enum** (≤22 bytes inline / `Rc<str>` beyond), after measuring
  `Rc<String>` as a regression (double allocation for small strings). O(1)-copy contract
  unchanged (23-byte memcpy or refcount bump).

---

## Phase-3 incidental decisions (recorded for transparency)

- **Backend B emits LLVM IR from the typed AST** (via llvmlite), mirroring Backend A's
  documented deviation — SIR remains the analysis IR. Scope: the numeric core (int/float/bool,
  full CPython arithmetic semantics incl. overflow traps, control flow, calls, print of
  int/bool/str literals). `serp llvm` JIT-executes; programs outside the core exit 3 with a
  pointer to `serp build`. Backend A (Rust) remains the full-language, static-binary path.
- **Strings are `Rc<str>`** (`SStr`) per §3.7 — O(1) copies; producing ops pay one extra copy
  (documented 0.6x on the string microbench, Phase-4 optimization target).
- **`range()` is a lazy iterator** in the runtime (was a materialized Vec).
- **Codon/mypyc benchmarking is host-blocked** (no Windows support / no cl.exe); the vs-Codon
  half of the Phase-3 milestone is carried by the alloc-churn benchmark achieving parity with
  handwritten Rust, to be re-run against Codon on a Linux/macOS host.
- **llvmlite** is a compiler-side dependency only (added to the venv); generated binaries and
  the shim are unaffected.

- **Runtime architecture:** all fatal runtime errors are `SerpErr` error values; generated
  functions return `Result<T, SerpErr>`; `try` lowers to stable labeled blocks (no closures,
  no unwinding) — implements D1's backend sketch.
- **`self` conventions:** methods must annotate `self: Ref[C]` or `self: Mut[C]`. `Owned`
  (consuming) self is deferred to Tier 2 (`SE202`).
- **Generic classes must declare `class C(Generic[T])`** — required for CPython parity
  (`C[int]` subscription at runtime). `from __future__ import annotations` is allowed and
  recommended for forward references (`self: Ref[C]` inside `C`).
- **Exceptions surface:** built-in exception classes only; no `try/else`; no `return` inside
  try-with-finally; no `break`/`continue` escaping a try; no `return/break/continue` in
  `finally`. Handler variables are Copy `exception` values.
- **New code `SE008 move-out-of-borrow`:** moving (a field) out of a `Ref`/`Mut` parameter —
  required for rustc agreement (E0507).
- **Mutation through a per-iteration loop Ref is `SE004`** — required for rustc agreement
  (loop variables are `&T` in the generated Rust).
- **Documented divergences added:** `repr` of a `Weak` field prints `<weak>` natively
  (CPython shim shows the referent); `sys.argv[0]` is the native binary path (CPython: the
  .py path); `upgrade()` can return `None` natively but never under CPython (D2 timing);
  mutating `sys.argv` is not supported (each read is an owned copy).

- **License:** MIT.
- **Version pin:** CPython 3.12 for spec grammar and CI (archive/research.md §4).
- **Error-code scheme:** `SE0xx` ownership, `SE2xx` types/subset — spec.md §12.
- **Package layout:** `shim/` holds the `serpentine-shim` distribution exposing import package
  `serpentine`; the compiler (`serpentine-lang`, Phase 1) will live in `compiler/`.
- **PyPI names:** `serpentine-lang` and `serpentine-shim` verified unregistered on 2026-07-17
  (`pip index versions` → no matching distribution). Actual registration + GitHub org
  requires account credentials — owner action.

## D10 — `PyVal` dynamic value type (Tier 2, 2026-07-22)

**Decision.** Add a compiler-known boxed dynamic value type, `PyVal`: an
immutable, refcounted, Copy handle over a tagged union of
None/bool/int/float/str/bytes/list/dict (lists and dicts hold `PyVal`s; dict
keys are str). It exists for exactly one purpose: stdlib APIs whose *return
types are decided at runtime* (json.loads, tomllib.loads, sqlite3 rows,
csv.DictReader, argparse's Namespace) cannot be expressed in the static Tier-0
type system, and without them the drop-in story has a hole in its center.

**What it deliberately trades.** Inside a `PyVal` there is no static typing —
`v["users"][0]["name"]` type-checks even when the data turns out to be an int
at runtime (you get the CPython TypeError/KeyError/IndexError instead of a
compile error). This is a *scoped* retreat from static typing at specific
library boundaries, not a general `Any`: PyVal supports only `[]` indexing,
truthiness, `==`/`!=` (Python cross-numeric and deep-container semantics),
`len()`, iteration, `in`, explicit extraction via `int()/float()/str()/bool()`,
and the `pyval_kind()` discriminator from the shim. No arithmetic, no ordering,
no mutation (item assignment is rejected; values are immutable), no dict-key
use, no attribute access. Escaping back into typed code requires an explicit
conversion, so the dynamic region stays visible in the source.

**Semantics.** Copy handle (like `Shared`/str): chained indexing and
re-binding never move or borrow. Implicit coercion *into* PyVal happens at
annotated boundaries (arguments, returns, assignments, list/dict literals under
a PyVal expectation) from None/bool/int/float/str/bytes and lists/str-keyed
dicts thereof; extraction *out* is always explicit. Under CPython the shim
aliases `PyVal = object` and values are the real Python objects, so every
operation is natively identical — the dual-run harness keeps both worlds
byte-equal. Backend A represents it as `Rc<PValRepr>` (prelude.rs); Backend B
as an opaque refcounted pointer with an `rt_pyval_*` extern family (rt.rs).

## D11 — argparse Namespace: indexing, not attribute sugar (2026-07-22)

**Decision.** serp-cli's `parse_args()` returns a dict-shaped `PyVal`; values
are read with `args["verbose"]` indexing. We deliberately did NOT add
attribute-access sugar (`args.verbose`) to `PyVal`.

**Why.** Attribute sugar can only be implemented on the type, not on one
value: every compiled `PyVal` (json.loads results, sqlite rows, ...) would
start accepting `.attr` — code that CPython rejects with `AttributeError` on
plain dicts. That breaks the dual-run guarantee in the compiled-accepts-more
direction, silently, everywhere PyVal appears. Indexing is symmetric: the
facade's CPython side returns the same dict, both worlds accept exactly the
same programs, and porting real argparse code is a mechanical
`args.x` → `args["x"]` rewrite that the checker points out at compile time.

**Also fixed here.** Parser errors print to stdout (the subset has no
stderr) before `sys.exit(2)`; usage/help/error text is pinned to argparse
3.11 (verified byte-identical for the supported surface).

## D12 — Global singletons live in the runtime, not the language (2026-07-22)

**Decision.** Libraries that need process-global mutable state (logging's
logger registry and configuration) hold that state in their **runtime core**
(`serp_log_core`: a str→str KV store + a stderr sink), not in Serpentine
module state. No language change: Tier 0 still has no mutable globals.

**Why this is sound.** The precedent is serp-random: MT19937's state has
always been a runtime static behind `mt_seed`/`mt_random`. Logging is the
same shape — `Logger` values in Serpentine code are plain immutable
dataclasses holding only a name; every read (`getEffectiveLevel`) and write
(`setLevel`) goes through the core at call time, so two `getLogger("x")`
results are behaviorally one logger. Identity itself is unobservable: the
subset rejects `is` on objects (SE207), so "same object or equal copies"
cannot be distinguished in-language.

**Scope.** This is a per-library carve-out implemented in the library's core,
not a general global-variable mechanism; the checker still rejects
module-level mutable state everywhere (SE206). Under CPython the delegate
holds the same state in a module dict, so dual runs stay byte-identical.
