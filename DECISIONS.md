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

---

## Phase-2 incidental decisions (recorded for transparency)

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
