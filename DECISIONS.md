# Serpentine — Design Decisions

> Resolutions of the open questions in RESEARCH.md §8, decided in Phase 0. Reopening one of
> these is a spec change.

## D1 — Exceptions × ownership (§8.1)

**Decision:** `try` body is a lexical sub-scope; all borrows created inside it die at
`except`/`finally` entry as well as at normal exit. At `except` entry every place is in the
join of its states over all raising points (maybe-moved ⇒ unusable, `SE001`). Unwinding drops
owned values along the unwind path using per-place drop flags. Runtime errors are error values
from day one so Tier-1 can make them catchable.
**Rationale & prototype:** `docs/exceptions-ownership.md`.

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
**Rationale:** RESEARCH.md §8.4's own proposal; threading before the checker is real would
multiply every design question.

## D5 — Compiler self-hosting (§8.5)

**Decision:** Kept as a **north-star, not a commitment.** The compiler is written in ordinary
Python (RESEARCH.md §4); no Tier decisions are made for self-hosting's sake.

## D6 — CPython interop boundary (§5.12, Phase 4)

**Decision:** **v0.1 refuses foreign imports** (`SE213` names the policy and points to
`docs/interop.md`). The deep-copy boundary (embed libpython, snapshot values both ways,
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

- **Tier-2 surface (SPEC.md §14):** str indexing/slicing (`s[i]`, `s[a:b]`, no step),
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
- **Version pin:** CPython 3.12 for spec grammar and CI (RESEARCH.md §4).
- **Error-code scheme:** `SE0xx` ownership, `SE2xx` types/subset — SPEC.md §12.
- **Package layout:** `shim/` holds the `serpentine-shim` distribution exposing import package
  `serpentine`; the compiler (`serpentine-lang`, Phase 1) will live in `compiler/`.
- **PyPI names:** `serpentine-lang` and `serpentine-shim` verified unregistered on 2026-07-17
  (`pip index versions` → no matching distribution). Actual registration + GitHub org
  requires account credentials — owner action.
