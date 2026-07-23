# Serpentine — Research & Design Document

> **Thesis:** Python source code, written under an ownership-and-borrowing discipline, can be
> ahead-of-time compiled to native machine code with **no garbage collector** — while the exact
> same file remains valid, runnable CPython. One codebase, two execution modes.

- **Name:** Serpentine (the snake mineral — Python semantics hardened into stone)
- **CLI:** `serp`
- **Status:** pre-implementation research

---

## 1. The Core Idea

A borrow checker is a *purely static* analysis: it rejects programs, but it never changes what an
accepted program does at runtime. This gives Serpentine its founding invariant:

> **The Dual-Execution Guarantee**
> Any program accepted by `serp check` produces the same observable behavior when
> (a) executed by CPython, and (b) compiled by `serp build` and run natively —
> modulo a small, explicitly documented list of divergences (§7).

Ownership is encoded exclusively through constructs CPython already ignores at runtime:

- **type annotations** (`x: Owned[list[int]]`) — inert metadata to CPython
- **decorators** (`@serpentine.native`) — identity functions in the shim package
- **a shim package** (`pip install serpentine-shim`) where `Owned`, `Ref`, `Mut`, `Shared` are
  no-op generic aliases, so the code imports and runs under CPython unchanged

This is "mypy for ownership, plus a codegen backend."

```python
from serpentine import Owned, Ref, Mut, move

def total(prices: Ref[list[float]]) -> float:      # immutable borrow
    return sum(prices)

def append_tax(prices: Mut[list[float]]) -> None:  # mutable borrow
    for i in range(len(prices)):
        prices[i] *= 1.19

def main() -> None:
    prices: Owned[list[float]] = [9.99, 4.50]
    print(total(prices))          # borrow ends after call
    append_tax(prices)            # exclusive borrow, then returned
    archive = move(prices)        # ownership transferred
    # print(prices)               # <- serp: ERROR use-after-move; CPython: would run fine,
    #                                  but the checker rejects the program *before* either runs
```

`move()` is `lambda x: x` in the shim. The checker treats it as a semantic move; CPython treats it
as nothing. Programs that pass the checker never observe the difference.

---

## 2. Prior Art — What Exists, What's Missing

| Project | AOT native | Ownership/no-GC | Dual-runnable | Notes |
|---|---|---|---|---|
| **Codon** | ✅ LLVM | ❌ Boehm GC | ⚠️ mostly | The blueprint for the AOT half. Static typing via duck-type inference, bidirectional IR. You've contributed — steal the pipeline lessons. |
| **Mojo** | ✅ MLIR | ✅ ownership + borrowing | ❌ superset, own stdlib | The blueprint for the semantics half. Study its `owned`/`borrowed`/`inout` argument conventions and ASAP destruction model. |
| **mypyc** | ✅ (C ext) | ❌ refcounting | ✅ | Best-in-class example of "annotations as the contract." |
| **Nuitka** | ✅ (C) | ❌ refcounting | ✅ | Compiles *all* of Python by embedding libpython — the opposite tradeoff. |
| **Cython** | ✅ (C ext) | ❌ refcounting | ⚠️ pure-Python mode | Shows how a shim/annotation dual-mode ships in practice. |
| **py2many** | ✅ via Rust | ✅ (rustc's checker) | ❌ | Proof the ast→Rust route works; rough error UX. |
| **Shed Skin / MatxScript / LPython** | ✅ | ❌ | ⚠️ | More evidence for the "restricted subset" approach. |

**The gap Serpentine fills:** nobody combines *deterministic memory (no GC) + borrow checking +
the same file runs under CPython*. Codon proves demand for the AOT half; Mojo proves demand for
the ownership half; the intersection is empty.

---

## 3. Language Design

### 3.1 The Subset (define it ruthlessly, on day one)

Serpentine compiles a **statically typed, ownership-disciplined subset**. Write the subset spec
*before* writing the compiler — scope creep is the #1 project killer here.

**Tier 0 (MVP):**
- `int`, `float`, `bool`, `str` (immutable → freely copyable), `None`
- `list[T]`, `dict[K, V]`, `tuple[...]` (owned, movable, borrowable)
- functions with full annotations; `if/while/for/return`; arithmetic; comparisons
- `move()`, `Owned/Ref/Mut` parameter conventions

**Tier 1:**
- `@dataclass`-style classes (fields, methods, no inheritance)
- `Shared[T]` — escape hatch: refcounted like `Rc<T>` (checker enforces no cycles via
  ownership DAG or requires `Weak[T]`)
- exceptions (see §8 — this interacts with ownership more than anything else)
- generics on functions/classes (monomorphized, like Codon/Rust)

**Tier 2:**
- protocols/traits, closures (capture-by-move vs capture-by-borrow rules), iterators as
  first-class borrows, `with` as RAII sugar

**Explicitly never:** `eval`/`exec`, monkeypatching, metaclasses, dynamic attributes,
runtime reflection, multiple inheritance, `globals()` mutation. Every AOT Python compiler
draws this line; draw it in the spec, not in bug reports.

### 3.2 Ownership Model (start smaller than Rust)

- Every value has exactly one owner; assignment of non-`Copy` types is a **move** —
  BUT: plain `a = b` moving would silently diverge from Python intuition, so require the
  **explicit `move()` marker** for transfers and make plain rebinding of a live owned value a
  checker *error*. Explicit > clever. This is Serpentine's key ergonomic difference from Rust.
- Borrows: any number of `Ref` XOR one `Mut`. Function-call-scoped first (borrows cannot be
  stored in structures in Tier 0/1) — this eliminates the need for named lifetimes entirely,
  which is the single biggest complexity cut vs Rust.
- Drops inserted at end of lexical scope (upgrade to ASAP/last-use drops later — Mojo does
  ASAP destruction and it simplifies lifetime reasoning).
- `str`/`int`/`float`/`bool`/`tuple`-of-`Copy` are `Copy` types: no move semantics, matches
  Python intuition for immutables.

### 3.3 Why no named lifetimes (initially)

Rust's lifetime annotations exist because borrows can be *stored and returned*. If Tier 0/1
forbids storing borrows in structs and restricts returned borrows to "derived from exactly one
argument" (elided, like Rust's elision rules), you get 90% of the safety with 10% of the checker
complexity. Add named lifetimes only if real programs demand them.

### 3.4 Call-Site Conventions

The parameter annotation decides what the caller gives up; ownership transfer is always visible
at the call site:

| Parameter | Call site | Meaning |
|---|---|---|
| `Ref[T]` | `f(xs)` | immutable borrow for the duration of the call |
| `Mut[T]` | `f(xs)` | exclusive borrow for the duration of the call |
| `Owned[T]` | `f(move(xs))` | ownership transfer — the `move()` marker is **required** |

Passing a live owned value into an `Owned` parameter without `move()` is a checker error —
consistent with the rebinding rule in §3.2: transfers are always spelled out in the source.
Copy types need no marker anywhere. Return values are always owned by the caller.

Builtin methods have fixed receiver/argument conventions:
- `len(xs)` — `Ref self`
- `xs.append(v)` — `Mut self`; `v` is `Owned`, so non-Copy elements need `xs.append(move(v))`
- `xs[i] = v` — `Mut self`; moves `v` in (marker required for non-Copy)

### 3.5 Places & Element Access

SIR tracks *places* (`x`, `x.f`, `x[i]`), modeled on rustc. Reading a place:

- **Copy element type:** `y = xs[i]` copies. No restrictions.
- **Non-Copy element type:** moving out of a container by index is **forbidden** — it would
  leave a hole (same rule as Rust's `Vec`). `move(xs[i])` is a checker error. Sanctioned ways:
  - `xs.pop()` / `xs.pop(i)` / `d.pop(k)` — remove *and* transfer ownership,
  - borrow in place: `f(xs[i])` into a `Ref`/`Mut` parameter, or `xs[i].method()`, borrows
    the element for the duration of the call,
  - `xs[i] = new_value` — overwrite; the old value is dropped.
- **Fields (Tier 1):** partial moves allowed — `move(x.f)` leaves `x.f` uninitialized and `x`
  unusable as a whole until reassigned. Field-sensitive tracking is Phase-2 work (§5, step 7).

`for x in xs:` takes a `Ref` borrow of `xs` for the whole loop body (this is exactly what
rejects `xs.append` during iteration, §6.6). The loop variable:
- Copy element type: `x` is a copy.
- Non-Copy: `x` is a `Ref[T]` valid for one iteration — it cannot be stored or moved.
  Mutating elements in Tier 0 is `for i in range(len(xs)): xs[i] = ...`; a `Mut`-borrowing
  iteration form is Tier-2 territory.

### 3.6 `Optional[T]` / `None`

`T | None` is **Tier 0** — real Python is unwritable without it (`dict.get` alone forces the
issue).
- Compiles to Rust `Option<T>` (Phase 1) / a tagged value with niche optimization (Phase 3).
- The checker does flow-sensitive narrowing on `if x is None:` / `if x is not None:` — the one
  permitted use of `is` (§7). Inside the narrowed branch, `x` is usable as `T`.
- No other unions in Tier 0. General `A | B` is Tier 2 at the earliest.

### 3.7 `str` Representation

`str` is semantically Copy (§3.2) — but a naive native `str` would make every copy an O(n)
memcpy, a hidden cost Python programmers won't expect. Proposal:
- Native `str` is an immutable refcounted buffer (`Rc<str>`-style): copy = refcount bump, O(1).
- This does not compromise the no-GC claim: immutable data cannot form cycles, so plain
  refcounting is exact and deterministic here — same status as Rust's `Rc`.
- Interning / small-string optimization are later perf work, not spec matters.
- The same representation decision applies to `bigint` if/when it lands.

### 3.8 Tier-0 Builtins Surface

Enumerate this in SPEC.md — "which builtins exist" is spec, not implementation detail.
Proposed Tier-0 list:

- **Functions:** `print`, `len`, `range`, `enumerate`, `sum`, `min`, `max`, `abs`, `str`,
  `int`, `float`, `bool`
- **Syntax:** f-strings (formatting must match CPython — see §7 repr rows)
- **`str` methods:** `split`, `join`, `strip`, `startswith`, `endswith`, `find`, `replace`,
  `upper`, `lower`
- **`list` methods:** `append`, `pop`, `insert`, `extend`, `clear`, `reverse`, `sort`
  (key-less only; `key=` needs closures → Tier 2)
- **`dict` methods:** `get` (returns `T | None` — the reason Optional is Tier 0), `keys`,
  `values`, `items`, `pop`, plus the `in` operator
- **I/O:** Tier 0 is `print` + `input`. `open()` is Tier 1: the file object's deterministic
  drop closes it — RAII for free, `with` becomes optional sugar (Tier 2). `sys.argv` /
  `sys.exit` are Tier 1 (the north-star JSON parser needs all three).

### 3.9 Runtime Errors Before Exceptions Exist

Tier 0 already has index-out-of-bounds, `KeyError`, division by zero, and (with 64-bit ints,
§7) overflow — but exceptions are Tier 1. Unspecced, this breaks the Dual-Execution Guarantee
on day one. Proposal — **fatal runtime errors**, the moral equivalent of `panic=abort`:

- Native binaries always bounds-check. No unsafe fast mode in v1.
- On a runtime error, the native binary prints the same error class and message as CPython
  (`IndexError: list index out of range`) to stderr and exits 1 — matching CPython's
  unhandled-exception exit status. Traceback *frames* are best-effort (documented divergence,
  §7).
- Integer overflow traps with `OverflowError` rather than wrapping — silent wraparound is
  exactly the kind of quiet behavioral drift §7 forbids.
- In Tier 0 these are uncatchable in both modes (no `try` in the subset yet). When Tier-1
  exceptions land they become ordinary catchable exceptions — so implement them as error
  values in the runtime from day one, not literal `abort()` calls, or Tier 1 forces a runtime
  rewrite.

### 3.10 Modules & Entry Point

**Imports.** `serp check` follows imports and sorts every module into one of three bins:
1. **Serpentine modules** (project files in the subset) — checked and compiled together.
   Whole-program compilation is fine for v1; monomorphization wants it anyway.
2. **The shim** (`from serpentine import ...`) — recognized and erased at compile time.
3. **Everything else** (stdlib, site-packages) — checker error at the import site in Tier
   0/1. This line moves only when Phase-4 interop lands.

**Module-level code.** Tier 0 allows imports, function definitions, and `Copy`-typed constants
at module level — nothing else. Arbitrary module-level statements are rejected: it keeps
"import has no side effects" true and sidesteps global-initialization-order entirely.

**Mutable globals** are rejected in Tier 0. Ownership of globals is a genuine design pit (Rust
makes it hard on purpose); revisit only if Phase-2 corpus data demands it.

**Entry point.** `serp build` recognizes the standard idiom:

```python
if __name__ == "__main__":
    main()
```

and makes `main()` the native entry point (or override with `serp build --entry`). CPython
behavior is untouched by construction.

---

## 4. Architecture

```
source.py
   │  ① Frontend: Python's own `ast` module (free parser, always syntax-current)
   ▼
Typed AST      ② Type checker: names→symbols, full-annotation enforcement,
   │              monomorphization of generics (no global inference in v1!)
   ▼
SIR            ③ Serpentine IR: CFG of basic blocks, explicit moves/borrows/drops,
   │              places (paths like x.f[i]) — closely modeled on rustc's MIR
   ▼
Borrow check   ④ Dataflow over SIR: initialized-places analysis + loan analysis
   │              (lexical scopes v1 → NLL-style liveness later)
   ▼
   ├──► ⑤a Backend A (Phase 1): transpile SIR → Rust → rustc
   └──► ⑤b Backend B (Phase 2): SIR → LLVM IR (llvmlite or inkwell)
```

**Frontend version pin:** `ast` output differs across CPython versions, so the spec grammar is
defined against one pinned version (propose 3.12+) and CI runs the frontend on that version
only. Raising the pin is a deliberate spec change, not an incidental upgrade.

**Implementation language decision:** write the compiler in **Python first** (frontend, type
checker, SIR, borrow checker are all symbol manipulation — iteration speed wins), with the
option to port hot paths or the whole thing to Rust once the design stabilizes. You know both;
premature Rust here costs months of iteration speed. (Counter-argument: if this is also a "get
deeper into Rust" project, write it in Rust from day 1 and accept slower iteration. Decide
consciously.)

**The Backend-A trick:** transpiling to Rust means *rustc is your oracle*. Your borrow checker
and rustc's must agree; every disagreement is a test case and a bug in yours. This is an
enormous development accelerant — you get a reference implementation of the hardest component
for free. Ship Phase 1 with rustc as the enforcement backstop, then make your own checker
authoritative and error messages Python-native.

---

## 5. Step-by-Step Roadmap

### Phase 0 — Spec (1–2 weeks of evenings)
1. Write `SPEC.md`: the Tier-0 subset grammar, the ownership rules as judgments
   ("after `move(x)`, `x` is uninitialized until reassigned"), the divergence list (§7).
2. Write 30–50 tiny programs *by hand* in `tests/accept/` and `tests/reject/` — each reject
   case annotated with the exact error you want (`use-after-move`, `mut-while-borrowed`, ...).
   **These tests ARE the spec.** Writing them first will change your design.
3. Publish the shim package skeleton (`serpentine-shim`) — 40 lines, but it locks the API.

### Phase 1 — Walking skeleton (the most important milestone)
4. `serp check`: ast → typed AST → SIR for the *minimal* language (ints, functions,
   `if/while`, lists, move/borrow). Lexical borrow checker.
5. `serp build` via Backend A (SIR → Rust source → rustc). Milestone: **fib.py and a
   list-manipulation program compile, run natively, and produce byte-identical stdout to
   `python fib.py`.** End-to-end beats feature-complete.
6. Differential test harness: every `tests/accept/` program runs under both CPython and the
   native binary, stdout compared automatically. This harness is your correctness backbone
   forever; build it now, not later.

### Phase 2 — Make the checker real
7. Grow the checker: field-sensitivity (`x.f` moved while `x.g` live), partial moves,
   loops (fixed-point dataflow — moves in loop bodies are where naive checkers break),
   `Shared[T]`.
8. Error messages: rustc-quality diagnostics with source spans, "value moved here" secondary
   labels, and suggested fixes. **For a language project, error UX is the product.** Budget
   real time for it.
9. Fuzz the frontier: run the checker over real small Python programs (Project Euler solutions,
   etc.) and catalog what idioms the subset rejects — this data drives Tier-1 priorities.

### Phase 3 — Native backend & benchmarks
10. Backend B: SIR → LLVM IR. Runtime: a small static library (malloc/free wrappers, str/list
    /dict implementations — study Codon's runtime layout here).
11. Benchmark suite vs CPython / Codon / mypyc / handwritten Rust. The headline claim to chase:
    *"Codon-class speed, without the GC."* Measure allocation-heavy workloads where Boehm GC
    hurts Codon — that's your differentiating benchmark.

### Phase 4 — Ecosystem reality
12. CPython interop for the native build (call into libpython for unported libraries — the
    boundary transfers ownership by deep-copy or refuses; design this carefully).
13. Tier-1 features by demand order from Phase-2 data. Editor integration (LSP) once the
    checker is stable — checker-as-library from day 1 makes this cheap.

---

## 6. Things to Look Out For (the traps, in priority order)

1. **Scope creep is fatal.** "Just one more Python feature" is how these projects die. The spec
   is a wall; changes to it are PRs against SPEC.md, even when you're the only contributor.
2. **Global type inference is a rabbit hole.** Codon spent enormous effort on bidirectional
   duck-type inference. Require annotations in v1; add inference in v3 if ever.
3. **Loops break naive borrow checkers.** `move` inside a loop body means the value is *maybe*
   uninitialized at the loop head — you need fixed-point dataflow, not a single pass. Write
   loop tests before writing the loop analysis.
4. **Exceptions × ownership** is your hardest semantic design problem (§8). Prototype it on
   paper in Phase 0, even though implementation is Tier 1.
5. **Aliasing is idiomatic Python.** `b = a; b.append(1)` is normal Python and a checker error.
   Expect the subset to feel restrictive; the differential-testing corpus (Phase 2, step 9)
   tells you which restrictions actually hurt vs which nobody hits.
6. **Iterator invalidation:** `for x in xs: xs.append(x)` must be rejected — a `for` loop takes
   a borrow of `xs` for its whole body. Easy rule, easy to forget.
7. **Closures capture by reference in Python.** Ownership rules for captures (move vs borrow,
   and borrows can't outlive the closure's scope) need explicit design; defer to Tier 2 but
   don't accidentally allow closures earlier.
8. **`str` interning / `id()` / `is`:** `is` on non-`None` values must be rejected or defined
   as a divergence — identity semantics differ between backends.
9. **Don't chase CPython bug-for-bug numerics.** Define `int` as arbitrary-precision (matching
   Python, like Codon chose NOT to — Codon's 64-bit ints are a known divergence pain point) or
   64-bit with documented overflow — but decide in the spec, and put it in the divergence list
   if you pick 64-bit. Recommendation: 64-bit `int` + explicit `bigint` type; pragmatism over
   purity, but it's your loudest documented divergence.
10. **Error-message time is not overhead.** Half of Rust's adoption is diagnostics. Same here.
11. **Name hygiene:** grab `serpentine-lang` on PyPI + GitHub org early. Note existing
    `serpentine`-adjacent PyPI packages — pick distinct distribution names (`serpentine-lang`,
    `serpentine-shim`) before someone else does.

---

## 7. Documented Divergences (native vs CPython) — draft list

| Behavior | CPython | Serpentine native | Verdict |
|---|---|---|---|
| Destruction timing | refcount + GC, `__del__` unordered | deterministic at scope end | Documented; `__del__` unsupported in subset |
| `id()` / `is` | object identity | no stable identity | Rejected by checker (except `is None`) |
| `int` overflow | arbitrary precision | 64-bit, traps `OverflowError` (+ `bigint` opt-in) | Loudest divergence — document hard |
| `//` and `%` on negatives | floor semantics (`-7 // 2 == -4`) | must match — codegen emits floor-div/mod helpers (Rust truncates!) | Fix in codegen |
| `bool` is an `int` subclass | `True + 1 == 2` | bools in arithmetic positions | Rejected by checker — write `int(b)` |
| container `repr` / f-string formatting | CPython repr rules | must match | Fix in runtime |
| unhandled runtime error | traceback + exit 1 | error class + message + exit 1 match; frames best-effort (§3.9) | Documented |
| `float` repr edge cases | CPython repr algorithm | must match — implement Ryū/grisu | Fix in runtime, not docs |
| dict ordering | insertion-ordered | must match — insertion-ordered impl | Fix in runtime |
| Stack depth / recursion | RecursionError at ~1000 | native stack, no limit | Documented |

Rule of thumb: **divergences must be things the checker can't observe programs depending on, or
loud spec-level decisions — never silent behavioral drift.**

---

## 8. Open Design Questions (decide during Phase 0)

1. **Exceptions:** unwinding must drop owned values along the unwind path (Rust panics do this).
   Do borrows across `try` blocks end at the `except` boundary? Proposal: a `try` body is a
   sub-scope; all borrows created inside it die at `except`/`finally` entry.
2. **`Shared[T]` cycles:** forbid statically (ownership DAG types) or provide `Weak[T]` and
   accept leaks on cycles (Rust's answer)? Proposal: Rust's answer; static cycle-freedom is a
   research project on its own.
3. **Returned borrows:** allow with Rust-style elision only (single borrowed param → derivable),
   or forbid entirely in Tier 0? Proposal: forbid in Tier 0, elision-only in Tier 1.
4. **Threading story:** the whole point of no-GC is a no-GIL native mode. `Send`/`Sync`-like
   rules fall out of the ownership model almost for free — but park it until Phase 3+.
5. **Compiler self-hosting:** is Serpentine-in-Serpentine a long-term goal? It's a phenomenal
   forcing function for language ergonomics, and a great demo. Keep it on the horizon.

---

## 9. Success Criteria

- **Phase 1:** dual-execution demo — one `.py` file, same output from `python x.py` and `./x`.
- **Phase 2:** checker catches all `tests/reject/` cases with rustc-quality messages; agrees
  with rustc on the transpiled corpus.
- **Phase 3:** ≥ Codon-class performance on numeric benchmarks; measurably better on
  allocation-heavy benchmarks (the no-GC dividend); binary with no libpython dependency.
- **North star:** a real program (e.g., a JSON parser or the Phase-1 test harness itself)
  written once, developed/debugged under CPython, deployed as a native binary.

## 10. Reading List

- Codon paper: *"A Compiler for High-Performance Pythonic Applications and DSLs"* (CC 2023) — pipeline & IR design
- rustc dev guide: MIR + borrow checker chapters (the two-phase-borrow and NLL RFCs: RFC 2094)
- Mojo docs: ownership & value semantics chapters (argument conventions, ASAP destruction)
- *"Oxide: The Essence of Rust"* (Weiss et al.) — formalized borrow checking, the cleanest model to implement from
- mypyc docs — annotations-as-contract, dual-mode packaging
- py2many source — ast→Rust lowering patterns (and what to avoid in error UX)
