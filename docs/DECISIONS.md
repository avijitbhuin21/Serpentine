# Serpentine — Design Decisions

> Resolutions of the open questions raised in the original research document (§8, archived — removed from the repo), decided in Phase 0. Reopening one of
> these is a spec change.

## D1 — Exceptions × ownership (§8.1)

**Decision:** `try` body is a lexical sub-scope; all borrows created inside it die at
`except`/`finally` entry as well as at normal exit. At `except` entry every place is in the
join of its states over all raising points (maybe-moved ⇒ unusable, `SE001`). Unwinding drops
owned values along the unwind path using per-place drop flags. Runtime errors are error values
from day one so Tier-1 can make them catchable.
**Rationale & prototype:** the exceptions × ownership paper prototype (archived, removed).

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
**Rationale:** the research doc §8.4's own proposal; threading before the checker is real would
multiply every design question.

## D5 — Compiler self-hosting (§8.5)

**Decision:** Kept as a **north-star, not a commitment.** The compiler is written in ordinary
Python (research doc §4); no Tier decisions are made for self-hosting's sake.

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

**v1 shipped (2026-07-23, blocker B3).** `from serpentine import spawn`:
`h = spawn(f, args...)` runs a concrete module function on a new thread and returns a
non-Copy `JoinHandle[R]`; `h.join()` delivers the result once (second join raises
`ValueError`; a panic/uncaught error in the thread re-raises at the join). v1 is
*stricter* than the full D9 model: no borrows cross the boundary at all — arguments and
returns must be **Send-by-copy** (`int`, `float`, `bool`, `str`, `bytes`; return may be
`None`), checked with new code `SE216 not-send`. Strings/bytes are deep-copied across
the boundary; the runtime's pending-error slot became thread-local. Dropping a handle
without joining detaches the thread (the shim uses daemon threads — join to guarantee
completion). Scoped borrows and `Sync[T]` (`Arc<Mutex>`) remain future D9 work.
**Update 2026-07-23 (Venom threading):** the socket handle table is now thread-safe
(Mutex'd table of per-socket `Arc<Mutex<SockRec>>`; blocking I/O holds only its own
socket's lock), so serp-socket/http-server/venom work from spawned threads. The
sqlite/logging runtime tables remain unsynchronized — keep those on one thread.
Thread-using programs skip the release-mode runtime-bitcode LTO (std::thread carries
module-level inline asm llvmlite cannot emit); they link the runtime as a plain
library, user code still gets O3.
**v2 shipped (2026-09-04, serp-threading).** `Thread(target=f, args=(...), name=, daemon=)`
and `Timer(interval, f, args)` are intrinsics (`from serpentine import Thread, Timer`,
re-exported by `serp_threading`): arguments are copied at construction, the thread runs
at `start()`, `join(timeout)`/`is_alive()`/`name`/`ident`/`daemon`/`cancel()` mirror
CPython, uncaught thread errors print to stderr, and the runtime joins every started
non-daemon thread when `main()` returns (CPython parity). The Send-by-copy rule gained
one case: a non-generic dataclass whose fields are all `int`/`float`/`bool` crosses the
boundary **by bitwise copy** when declared `Owned[C]` on the target (the caller keeps its
value) — this is how runtime-handle objects (`Lock`, `Event`, `Queue`, …) reach worker
threads. Sync primitives live in `Mutex`/`Condvar` tables in the runtime and are
identified by `int` handles; queue items are PyVal trees deep-copied across threads.
Still future: `class Worker(Thread)` + `run()`, `Sync[T]`/shared mutable objects.

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
- **Version pin:** CPython 3.12 for spec grammar and CI (research doc §4).
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

## D13 — Decorators are registration-only (blocker B2, 2026-07-23)

**Decision.** `@deco` / `@deco(args)` on module-level functions is supported
with **registration semantics**: the decorated name stays bound to the
original function, and every decorator application must produce a `Callable`
of the exact decorated signature (typechecked via a synthesized annotated
binding). Decorators are expected to return the function they receive; a
decorator that returns a *different* wrapper diverges from CPython and is the
programmer's contract violation, same class of rule as `__enter__` must
`return self`.

**Lowering.** The frontend collects decorations per module, synthesizes a
`_serp_deco_<module>()` function holding the applications (bottom-up per def,
source order per module), and injects calls to those functions at the top of
the entry function in CPython import order (imported modules first, entry
last). Under CPython the decorators run at import time — observably the same
point, since module level has no other executable statements.

**Caveat.** With several *factory* decorators stacked on one def, CPython
evaluates all factory expressions before applying, while Serpentine evaluates
each factory at its application; registration decorators should not depend on
cross-decorator evaluation order.

## D14 — async/await is eager (blocker B6, 2026-07-23)

**Decision.** `async def` compiles to a plain function; `await f(...)` runs
the call immediately. The checker enforces that every call to an async
function is **directly awaited** (or is the sole argument of `asyncio.run`),
and async functions cannot be used as values. Under that restriction the
program has exactly one runnable task at every point, so CPython's event loop
executes the same depth-first order — dual runs stay byte-identical.

**Supported asyncio surface.** `import asyncio`, `asyncio.run(coro())`
(including in the entry guard), and `await asyncio.sleep(x)` (lowered to the
runtime sleep). Everything else (`gather`, `create_task`, `wait`, …) is
refused with SE201: those introduce real concurrent tasks, which need a true
event loop (or D9 threads) — deferred until an async runtime is designed.

**Server-level event loop shipped (2026-07-23, Venom).** While *language* tasks
stay eager, the runtime gained the reactor half: non-blocking sockets
(`set_nonblocking`, `accept_nb`) and OS-level readiness (`poll_ready` —
WSAPoll on Windows, poll(2) on unix; TLS decrypted-buffer pre-check).
Venom's `serve_async` is a pure-Serpentine event loop over these: one thread
multiplexes any number of keep-alive connections, uvicorn-style, with the
listener in every worker's poll set (idle workers wake instantly and accept
ONE connection per wake, spreading load). A future task runtime (fibers or
state machines) can reuse this reactor to upgrade `await` from eager to
suspending.

## D15 — Single inheritance via flattening; build-time test discovery (blocker B5, 2026-07-23)

**Supersedes the same-day rejection** (B5 was first closed by rejecting
inheritance and reflection outright; reopened at the user's direction to ship
a unittest-style `serp-test`). The conflicts the rejection named are *avoided*
rather than solved:

**Decision.** **Single inheritance of `@dataclass` classes** with
mixin/textual semantics: `class Sub(Base)` makes the typechecker FLATTEN the
base into the subclass before member collection — base fields first (a
subclass may re-declare a base field, keeping its base position, CPython
dataclass order), then non-overridden base methods as AST copies with the
`self` annotation retargeted to the subclass. Inherited bodies are re-checked
in the subclass's module (they must resolve there — builtins, params, and
program-global exception names always do). Consequences, by design:
- **No subtyping**: a `Sub` is not assignable to `Ref[Base]`; no vtables, no
  virtual dispatch — every class stays a standalone monomorphized struct, so
  **both backends are unchanged**.
- No `super()`; overriding replaces. No generic bases, no multiple bases,
  cycles rejected. (`@staticmethod`s were not inherited originally; D16 made
  statics and classmethods inherit.)
- Field-less classes are now legal (a base can be pure behavior, e.g.
  `TestCase`).

**Test discovery is build-time, not reflective.** `serp test` finds
`TestCase` subclasses in the checked program (the compiler already knows
them), generates a runner module per test file (fresh instance + setUp/
tearDown per `test*` method, unittest-style FAIL/ERROR lines and summary),
builds and runs it natively, then deletes it. `AssertionError` joined the
builtin exceptions (direct `Exception` child — no prelude/runtime change).

## D16 — Build-time field-table intrinsics; `Annotated`/`Field` metadata; `classmethod` (molt LB1/LB3/LB4, 2026-07-26)

**Decision.** The compiler exposes its class field table to generated code
through three **generic, library-agnostic intrinsics** — it learns nothing
about pydantic:
- `fields_of(obj) -> dict[str, PyVal]` — the instance's fields as a PyVal
  dict, recursing into class-typed fields (also inside `list`/`dict`/`tuple`).
- `fields_json(cls) -> str` — the class's build-time field table (name,
  declared type, defaulted-or-not, folded default, `Field()` metadata) as a
  JSON string, so libraries parse a *value* instead of needing reflection.
- `fields_build(cls, d) -> cls` — construct an instance from a
  `dict[str, PyVal]` with strict per-field kind checks.

Each call site is lowered to an ordinary generated Serpentine function
synthesized from that class's field table (`fieldsyn.py`), so **both backends
compile them like user code** and no runtime type information exists. Combined
with D15 flattening, one `fields_of(self)` line in a base class is
monomorphized per subclass: `self` retargeting makes the intrinsic expand
against the subclass's own fields.

**`Annotated[T, ...]` is parsed** and its extras are kept as build-time
metadata; a **call in field-default position** (`x: int = Field(0, gt=0)`) is
recognized and its folded keyword/positional arguments are recorded in
`ClassInfo.field_meta` instead of being rejected as a non-constant default.
`default_factory=list`/`dict` gives per-instance empty containers.

**`@classmethod` is supported** and, unlike `@staticmethod` before it, both
`classmethod`s and `staticmethod`s are now inherited through flattening. `cls`
is a build-time binding (the class the call resolves to), not a runtime value:
`cls(...)` constructs, `cls.other()` dispatches, and `Self` is the return
annotation. Types are still not values — `type[T]` does not exist.

**Consequence for Backend B.** Coercing a *place* (name/field/element) to
`PyVal` is a read, not a move: llvmgen requests it in borrow mode, matching
Backend A's clone. Reading it in value mode used to neutralize the source,
which silently emptied container fields after the first `model_dump()`.

## D18 — Class-body registration decorators, hook intrinsics and `model_config` (molt LB2, 2026-07-26)

**Decision.** Class bodies gain two build-time-only extensions, both
library-agnostic:

1. **Registration decorators on methods.** A method decorated with
   `@field_validator(*names, mode=...)` or `@model_validator(mode=...)` keeps its
   body and loses the decorator; the frontend records
   `{kind, mode, fields, method}` against the class. Decorator arguments must be
   string literals and `mode` must be `'before'`/`'after'` — anything else is a
   build error (SE201). Hooks are inherited through D15 flattening, minus
   methods the subclass redefines. Decorators still cannot *change* behaviour
   (D13); they only register.
2. **Foldable class-body assignments.** `model_config = ConfigDict(...)` (or
   `dict(...)`) is folded into `ClassInfo.config` instead of being rejected, and
   is inherited unless the subclass overrides it.

Three intrinsics expose the table to generated code, lowered to synthesized
functions exactly like D16's: `hooks_json(cls) -> str` (the hook table),
`run_hook(cls, name, v) -> PyVal` (dispatch to a lifted validator classmethod by
name) and `run_hook_self(instance, name) -> None` (dispatch to an after-model
method through a `Ref`). `fields_json` grew a `"config"` key so one parse carries
fields + config. Orchestration — ordering, error accumulation, honouring config —
stays in the library.

**Why dispatch by name instead of function values.** The hook set is known at
build time, so the generated dispatcher is a chain of string comparisons over
that class's own methods; no function pointers, no runtime lookup, and validators
keep normal Serpentine signatures (`PyVal -> PyVal`).

**Divergence.** Validators receive exactly one `PyVal` — pydantic's
`ValidationInfo` (`info.data`, `info.field_name`, `info.context`) is not passed.
`mode="wrap"`/`"plain"` and serializer hooks are unimplemented, not blocked.


## D19 — Mapping unpacking, attribute-write hooks and function refs in metadata (molt LB8/LB13/LB14, 2026-07-27)

**Decision.** Three build-time-only extensions, all library-agnostic, close the
last cheap molt blockers:

1. **`**mapping` at call sites (LB8).** A `**` argument is expanded at
   type-check time. A dict *literal* is expanded to positional keyword
   arguments; `Model(**mapping)` on a model class is lowered to the D16
   `fields_build` helper. Mixing positional/keyword args with `**mapping`, or
   using `**mapping` on a plain function, is SE201 — the callee's parameters
   must be resolvable at build time.
2. **Attribute-write hooks and frozen classes (LB13).** `@dataclass(frozen=True)`
   is accepted (`Module.frozen_classes`, `ClassInfo.frozen`, inherited); writing
   a field of a frozen instance is SE201. `__setattr__` joins `ALLOWED_DUNDERS`
   and field writes are rewritten to route through it when a class defines one.
   Construction and `__post_init__` bypass the hook — in the compiler by
   construction, in the shim via `_bypass_setattr_in_init`. A fourth field
   intrinsic, `fields_set(obj, name, value)`, writes one field by name with the
   same strict coercion as `fields_build`.
3. **Foldable function references in metadata (LB14).** A bare function name in
   `Field()`/`ConfigDict()`/`Annotated[...]` folds to a `FnRef`, and a call
   inside `Annotated` is recorded as `{"call": ..., "args": [...]}`. Both ride
   into `fields_json` (`{"__fn__": name}`), and `run_hook` dispatches
   module-level functions as well as classmethods. Referenced functions must be
   visible `(v: PyVal) -> PyVal` functions in the class's module (SE214/SE201).

**Why.** Each is a general language capability, not a pydantic feature: the
library gets `Model(**data)`, `frozen=True`, `validate_assignment`,
`AfterValidator`/`BeforeValidator` and `alias_generator` with no new intrinsics
beyond `fields_set`.

**Divergence.** `frozen=True` in `model_config` is enforced by molt's
`__setattr__` at runtime; `@dataclass(frozen=True)` is the build-time form and
rejects writes at compile time. LB11 (`TypeAdapter`/`create_model` — runtime
reflection) and LB12 (`Decimal`) stay declined.

## D20 — `set[T]` is an insertion-ordered Copy-element container (molt LB7, 2026-07-27)

**Decision.** `set[T]` (and `frozenset[T]`, an accepted alias) is an owned
container with the same representation as `list[T]` in both backends — a
contiguous buffer with linear-scan uniqueness. Elements must be Copy types, like
dict keys: sets of lists or of `PyVal` are SE201. Iteration and `repr` follow
**insertion order**, exactly as dicts do (D8), not CPython's hash order.

**Why.** The set operations Serpentine needs (`add`/`in`/set algebra) are
O(n) on the small sets real code uses, and reusing the list ABI means no new
runtime layout, no hashing contract for user types, and one shared drop/clone/eq
path. Insertion order keeps the two backends byte-identical and matches the
existing dict decision.

**Divergence.** `print(s)` on a set prints in insertion order, so it can differ
from CPython, which prints in hash order; empty sets print `set()`. `set.pop()`
removes the *first* inserted element rather than an arbitrary one. Programs that
must match CPython byte-for-byte should print `sorted(s)`.

## D21 — Enums are C-like constant member sets, lowered to ordinals (molt LB6, 2026-07-27)

**Decision.** `class C(Enum | IntEnum | StrEnum)` is a distinct Copy type
`TEnum`, whose body may contain only constant `NAME = <int|str>` members (plus
docstrings). Members are ordinals at runtime: a Rust `enum` in Backend A, an
`i64` index in Backend B. Supported surface is `C.MEMBER`, `.value`, `.name`,
`C(value)` lookup (raising `ValueError` on a miss), `==`/`!=` against the same
enum, and use as a dict key, set element, or field type. `str()`/`repr()` follow
CPython 3.11+: plain enums print `C.MEMBER`, `IntEnum`/`StrEnum` print their
value, and `repr` is `<C.MEMBER: value>`.

**Why.** Enums are pervasive in pydantic models and in ordinary code, but the
dynamic half of `enum` (methods on members, `auto()`, aliases, `_missing_`,
functional creation, iteration over the class) needs runtime class objects that
Serpentine deliberately does not have. Constant member sets cover the field-type
use case at zero cost and stay a Copy scalar, so enums flow through containers
and struct fields without ownership rules.

**Divergence.** Methods, `auto()`, value aliases, mixed int/str members, empty
bodies, and iteration over the enum class are SE201. Ordering comparisons are
SE214 even for `IntEnum` — compare `.value`. Members are not `int`/`str`
subclasses: an `IntEnum` member is not accepted where an `int` is expected.

## D22 — A user `__init__` is a factory desugar with straight-line definite assignment (molt LB10, 2026-07-27)

**Decision.** A class may define `__init__(self: Mut[C], ...) -> None`. It is not
a method: the checker rewrites it into a module-level factory
`_serp_init_C(...) -> C` whose body hoists each `self.f = value` into a local of
the field's declared type and ends with the ordinary positional constructor, and
every `C(...)` call site is retargeted to that factory. The body must assign
**every field exactly once, at the top level** — assignments nested in `if`/loop/
`try` blocks, duplicate assignments, reading a field before it is assigned, early
`return`, and any use of `self` other than `self.<field>` are errors. Missing or
early-read fields are the new **SE217 uninitialized-field**. Both backends are
untouched.

**Why.** Rust has no partially initialized value, so the honest lowering is
"collect the writes, then build". Restricting to straight-line assignment makes
definite assignment a two-line check instead of a dataflow pass, and the desugar
reuses the existing ctor path (moves, coercions, generics, `repr`) for free.
CPython agrees on semantics: `@dataclass` keeps a user-written `__init__` and
never overwrites it, so the differential harness stays byte-exact.

**Divergence.** `__init__` is rejected on generic classes, on frozen classes, and
alongside `__post_init__`, `__setattr__` or validator hooks — each of those only
runs for the generated constructor. `C(**mapping)` is rejected for a class with
`__init__`. Conditional initialization is expressed with a ternary or a local
computed before the assignment.

## D23 — Generic classes may inherit one non-generic base (molt LB9, 2026-07-27)

**Decision.** `class Page(Base, Generic[T])` is accepted: exactly one plain
`@dataclass` base plus one `Generic[...]` base. Flattening (D15) copies the
base's fields and methods into the subclass unchanged — the base is non-generic,
so nothing needs substituting — and the subclass's methods monomorphize per
instantiation like any other generic class. The field-table intrinsics accept an
*instantiated* class: `fields_of(p)`, `fields_json(Page[int])` and
`fields_build(Page[int], data)` key their synthesized helper on the
instantiation (`_serp_fbuild_Page__int`) and substitute the class's type
arguments into the field table before rendering it.

**Why.** Generic models (`Page[T]` over `BaseModel`) are the last structural gap
between Serpentine dataclasses and pydantic's generic models, and both halves
already existed — single-inheritance flattening and class monomorphization. The
work was letting them meet and teaching the intrinsics to speak in
instantiations.

**Divergence.** Inheriting *from* a generic class (`class IntBox(Box[int])`) is
SE201: the base's members would need substitution while flattening. The
validator-hook intrinsics (`hooks_json` / `run_hook`) still require a
non-generic class. In CPython, the shim's auto-dataclass `__init_subclass__`
now chains to the inherited hook so `typing.Generic` still records
`__parameters__`.

## D24 — General unions are closed, runtime-tagged sums (molt LB5, 2026-07-27)

**Decision.** `A | B` / `Union[A, B]` is Tier 0. A union is a closed sum whose
members must be distinguishable at runtime; `isinstance(x, T)` is the only
narrowing form and is a pure tag test. Members are canonically ordered by
spelling, so `int | str` and `str | int` are one type, and a two-member sum with
`None` still collapses to `Optional[T]` (D-era optionals are unchanged). Backend
A emits a Rust `enum U_int__str { V0(i64), V1(String) }` with generated
`is_i`/`as_i`/`mut_i`/`into_i` accessors and a `PyShow` impl; Backend B emits a
flat tagged struct `{ i8 tag, member0, member1, ... }` and gep's the narrowed
slot. A member widens into the union implicitly at every annotated boundary
(assignment, argument, return, element); the reverse and union-to-union widening
do not exist. Any non-tag operation on an unnarrowed union is `SE210
unnarrowed-union`; two members sharing a runtime kind are the new `SE218
ambiguous-union`. The field-table intrinsics gained a `{"k":"union","members":
[...]}` schema node, an isinstance-dispatched dump and a `pyval_kind`-dispatched
build, mirrored in the shim.

**Why.** pydantic models are full of `int | str`, `str | Path`, discriminated
unions and `list[A | B]`; without a real sum type molt would have had to demote
every such field to `PyVal` and lose the compiler's checking. Tagging by runtime
kind (rather than by a declared discriminator field) keeps `isinstance()` — the
form Python programmers already write — as the single narrowing mechanism, and
keeps both backends honest with no runtime type information.

**Divergence.** `list[int] | list[str]`, `dict | Point` and any two dataclass
members are rejected (SE218) even though CPython can tell them apart. `float | T`
unions accept an `int` argument and store it as the float member, where CPython
would keep an `int` — annotate the call site with a float literal. `isinstance()`
is *not* a general predicate: it only tests union-typed names and one-level
fields (SE201 otherwise), and its second argument must be a member (SE214).

## D25 — Classmethods of a generic class are called on an instantiation (molt LB9, 2026-07-27)

**Decision.** Inside a `@classmethod` of `class Page(BaseModel, Generic[T])`,
`cls` and `Self` mean `Page[T]`, which makes every such classmethod a template
even when no parameter mentions `T`. It is monomorphized at the call site from
an explicit instantiation — `Page[int].model_validate(data)` — with the class's
type arguments seeded into the substitution before the arguments are unified;
the field-table and hook intrinsics accept the instantiated class and key their
synthesized helpers on it. A bare `Page.model_validate(...)` on a generic class
is `SE214` and names the required form. The CPython shim keeps parity by making
`Model[int]` a real cached subclass with the typevars substituted into its
annotations, so `cls` inside the classmethod carries the binding there too.

**Why.** Without this, generic models could only be built through the free
`fields_build(Page[int], data)` form: pydantic's whole surface is classmethods
(`model_validate`, `model_json_schema`, `parse_obj`), and `Page[int].m()` is
what users write. Seeding the substitution from the receiver is the only place
the binding can come from — the arguments of `model_validate(obj: PyVal)` say
nothing about `T`.

**Divergence.** The receiver must be written out at the call site; there is no
inference of `T` from the argument value, and `Page[int]` cannot be stored in a
variable and called later. Under CPython, `Page[int]` is a subclass rather than
a `typing` alias, so `type(x) is Page` is false for instances built through it
and dataclass `__eq__` treats `Page[int]` and `Page[str]` instances as unequal.

## D26 — The molt language-blocker programme is closed; LB11 and LB12 are permanent (2026-07-27)

**Decision.** LB1–LB10, LB13 and LB14 are implemented (D16, D18, D19, D20–D25) and the
blocker list is now closed. The two remaining entries are rejected outright rather than
deferred:

- **LB11 — runtime reflection / dynamic class creation.** Rejected. Serpentine has no
  runtime type objects: a class is a build-time description that is monomorphized away, and
  the field/hook tables (D16, D18) are synthesized *per class at compile time*. `create_model`,
  `TypeAdapter` over an arbitrary runtime type, `arbitrary_types_allowed`,
  `__get_pydantic_core_schema__`, `json_encoders` and `extra="allow"` attribute access all
  require constructing or inspecting types after the compiler has run, which the AOT model
  cannot express at any cost short of embedding an interpreter.
- **LB12 — `Decimal` / arbitrary-precision numerics.** Rejected for the language. `int` is a
  trapping `i64` and `float` is IEEE-754 binary64; adding a bignum/decimal *core* type would
  change the numeric tower, every backend's arithmetic lowering and the `PyVal` encoding for
  one library's field type. If exact decimals are wanted later they arrive as an ordinary
  library struct (coefficient + exponent over `i64`), not as a language change.

Both become documented divergences in `libs/serp-molt/README.md` and stay listed with `[L]`
in `docs/libraries/molt.md` so the gap is visible rather than silently missing.

**Why.** Leaving two blockers "open" implied more language work was queued behind molt, when
in fact both conflict with decisions the language is built on (no runtime type information,
fixed-width trapping integers). Closing them turns an open-ended list into a finished one and
moves the remaining pydantic gaps to where they belong — the library backlog.

**Divergence.** pydantic code using `create_model`, `TypeAdapter(SomeRuntimeType)`,
`extra="allow"` attribute reads or `Decimal` fields does not port; it must be restructured
around declared models and `int`/`float`/`str` fields.

## D27 — Serializer / computed-field hooks are three more registration decorators (2026-07-27)

**Decision.** The D18 hook mechanism gains three decorator kinds and three dispatch
intrinsics rather than a serializer-specific feature:

- `@field_serializer("f", ...)`, `@model_serializer` and `@computed_field` (over a
  `@property`) are recorded in `mod.class_hooks` exactly like the validator decorators, with
  the hook record also carrying the method's `args` count.
- `run_hook_val(obj, name, v)` dispatches a field serializer (instance + one value),
  `run_hook_get(obj, name)` dispatches a zero-argument method (a model serializer or a
  computed field) and `run_hook_info(cls, name, v, info)` dispatches a **two-argument**
  validator, so `ValidationInfo`-style hooks are expressible.
- Arity is decided at build time from the recorded `args` count: a one-argument validator
  keeps going through `run_hook`, a two-argument one through `run_hook_info`.

`fieldsyn` renders all six dispatchers the same way (`hook`, `hookself`, `hookget`,
`hookval`, `hookinfo`), so both backends compile them as ordinary user functions.

**Why.** Serializers are the mirror image of validators; adding a parallel mechanism would
have duplicated the hook table, the shim bookkeeping and the dispatcher synthesis. Passing
the *arity* through the table (instead of inventing a second decorator per shape) keeps the
compiler pydantic-agnostic: any library can register a method and dispatch it by name.

**Divergence.** `ValidationInfo` is a `PyVal` mapping (`info["data"]`, `info["field_name"]`),
not an object; `info.context` is absent (it would need LB11). `mode="wrap"`/`"plain"`
validators still do not exist — they need the inner validator as a callable value.

## D28 — Module-level type aliases are expanded before type checking (2026-07-27)

**Decision.** A module-level assignment whose value is a type expression —
`PositiveInt = Annotated[int, Field(gt=0)]`, `Pair = tuple[int, int]`, `Num = int | float` —
is recognized by the frontend, stored in `Module.type_aliases`, and substituted into every
annotation in the program by `expand_type_aliases()` before the checker runs. Aliases may
reference other aliases (bounded expansion depth); a name that is not a type expression stays
an ordinary constant.

**Why.** Constrained-type families (`PositiveInt`, `HttpUrl`, `EmailStr`) are *the* pydantic
spelling for reusable field constraints, and every one of them is `Annotated[T, Field(...)]`.
Expanding aliases textually before checking means no new type-system machinery: the checker
and both backends only ever see the fully written-out annotation.

**Divergence.** Aliases are build-time text, not runtime objects: they cannot be passed as
values, and `conint()`/`constr()` (aliases produced by a *call*) remain unsupported.

## D29 — A computed field carries its return schema, and the JSON Schema has a `mode` (2026-07-27)

**Decision.** A `@computed_field` hook record gains a `ret` entry: the field-table schema of
the method's return annotation, produced by `field_type_schema()` in the compiler and by
`_hook_ret()` (late `get_type_hints`) in the shim. `model_json_schema(mode="serialization")`
reads it and emits each computed field as a `readOnly` property that is also `required`,
matching pydantic; the default `mode="validation"` schema omits them.

**Why.** Computed fields already showed up in `model_dump`, so a schema that described the
dumped shape was wrong. pydantic solves this with `mode=`, and the hook table was the only
place that knew a computed property's type.

**Note.** The shim must resolve the annotation *late* — under `from __future__ import
annotations` a decorator sees a string, and model classes are not yet defined at decoration
time.

## D30 — A union field with two model members is rejected, not silently mis-dispatched (2026-07-27)

**Decision.** `field_type_schema()` raises `SE201` for a union whose members include more
than one class (`Cat | Dog`). Union validation and union construction both dispatch on the
input's runtime `PyVal` kind (D24), and every model arrives as `"dict"`, so the member cannot
be chosen. Real support needs `Field(discriminator=...)` — a tag read from the input and a
tag-driven branch in `fieldsyn`'s builder.

**Why.** The previous behaviour was an internal `AssertionError` from
`fieldsyn._union_default()`. A union local is now branch-initialized (annotation on the first
branch only) instead of pre-seeded with a member default, which also removes the requirement
that some member have a cheap literal default.

## D31 — Temporal and UUID fields are recognized by class name in the library, not the compiler (2026-07-27)

**Decision.** `date`, `datetime`, `timedelta` and `UUID` fields reach molt as ordinary
`{"k":"model","class":"date"/"Dt"/"timedelta"/"UUID",...}` field-table nodes. molt matches on
that class name: a non-dict input is parsed (ISO text for the three temporal types, any of the
four spellings for `UUID`, a number of seconds for `timedelta`), the dump path re-emits ISO
text (seconds for `timedelta`), and the JSON Schema emits `format: date`/`date-time`/`uuid`.
The compiler learns nothing about these classes.

**Why.** The alternative — a compiler-side list of "known library classes" — would have hard-
wired serp-datetime and serp-uuid into the language. A class-name match inside molt keeps the
field table generic and costs one branch on the validation path.

**Divergence.** Naive values only (serp-datetime has no timezones), and a user class named
`date`/`datetime`/`UUID`/`timedelta` used as a molt field type would be treated as temporal.
`timedelta` validates from and dumps to a number of seconds, matching pydantic's JSON mode.

## D32 — Self-referential models resolve cycle stubs at validation time (2026-07-27)

**Decision.** A back-reference in a field table is emitted as
`{"k":"model","class":"Node","cycle":true,"fields":[]}`. molt walks the root spec once per
validation entry point, collects every non-cycle model node into a class-name → spec table,
and swaps a stub for the real spec wherever the walk meets one. The JSON Schema emits a
`$ref` to the class name; the CPython shim's `_build_model` re-reads the class's own field
table when it is handed a stub.

**Why.** The field table is a finite tree, so a recursive type has to be cut somewhere; cutting
it with a named stub and re-joining it in the library keeps the intrinsic total and makes the
recursion depth a property of the *input* rather than the type.

## D33 — `Strict*` types are `Annotated[T, Field(strict=True)]` (2026-07-27)

**Decision.** `StrictInt`, `StrictFloat`, `StrictBool`, `StrictStr` and `StrictBytes` ship as
D28 aliases carrying a `strict` metadata key; the validator checks the runtime kind before any
lax coercion and emits the ordinary `int_type`/`float_type`/… error when it differs.

## D34/D35 — `Field(exclude=True)` and `model_json_schema(by_alias=)` (2026-07-27)

**Decision.** The dump walk (`_out_model`/`_out_value`, which replaced the alias-only walk)
skips fields whose metadata carries `exclude`, and applies aliases, temporal formatting and
nested-model recursion in one pass. `model_json_schema(by_alias=True)` is the default, as
upstream; `by_alias=False` emits declared field names.

## D36 — `info["context"]` is the `PyVal` answer to `info.context` (2026-07-27)

**Decision.** `model_validate(obj, context=...)` / `model_validate_json(text, context=...)`
thread a `PyVal` through every `run_hook_info` dispatch, where it appears as
`info["context"]` (`None` when unset). This is the `PyVal`-only divergence D27 anticipated;
LB11 is not needed for it.

## D37 — A failing union reports per-member errors (2026-07-27)

**Decision.** When no union member matches, molt re-runs each member's validation in isolation
and appends its errors under `loc + [member tag]`, where the tag is the member's class/enum
name or type kind, instead of emitting a single `union_type` error. The *dispatch* order is
still by runtime kind, not pydantic's smart-union order.

## D38 — Class operators are first-class expressions: comparison dunders may return objects, `&`/`|`/`^`/`~` overload, operator results are places (2026-09-06)

**Decision.** For a **class** left operand, `<`/`<=`/`>`/`>=` desugar to the class's
`__lt__`/`__le__`/`__gt__`/`__ge__` and the comparison expression takes **the dunder's return
type** — `bool` is no longer required. `&`, `|`, `^` desugar to `__and__`/`__or__`/`__xor__` and
unary `~` to `__invert__` (class operands only; the bitwise operators stay rejected on scalars).
The result of a class `__getitem__`, comparison, binary or unary operator is a **fresh owned
value**: assigning it (`sub: Series = df[key]`) is not a move-out-of-container (no SE006), and
attribute access on it (`df["a"].values`, `(s > 1).values`) materializes the temp in both
backends. `==`/`!=` remain the dataclass-generated structural equality and cannot be overloaded
(pandas-style `.eq()`/`.ne()` methods are the spelling).

**Why.** The Scales (pandas) flagship needs boolean-mask objects: `df.loc[(df["a"] > 1) &
~(df["b"] < 3)]`. The typecheck-level `op_calls` desugar already made this a backend-free
change; the only rule that stood in the way was the `require=BOOL` on comparison dunders,
which existed for narrowing — narrowing still applies when the dunder *does* return `bool`.

**Ridden along (codegen fixes surfaced by the same library).** Backend A now evaluates the value
of `x[i] = expr` / `d[k] = expr` / `obj[k] = expr` into a `let` temp before taking the `&mut`
container borrow (Python evaluation order; rustc E0502 on `body[i] = body[i] + s`,
`counts[k] = counts[k] + 1`, `fr["c"] = fr["a"] + 1`), and both backends type a comprehension
by its **expected** container type when one is known, so `out: list[PyVal] = [isna(v) for v
in xs]` coerces each `bool` element (Backend A: rustc type error; Backend B: silent layout
mismatch and a `0xC0000005`). Accept test: `tests/accept/094_class_cmp_bitwise.py`.

## D39 — `__eq__`/`__ne__` overloads and reflected arithmetic on classes (2026-09-06)

**Decision.** A class may define `__eq__`/`__ne__`; when it does, `a == b` / `a != b` with that
class on the left desugars to the method and takes its return type (so `df["a"] == 1` is a
boolean-mask Series). Classes without them keep the dataclass-generated structural equality.
`scalar <op> obj` dispatches to `obj.__radd__/__rsub__/__rmul__/__rtruediv__/__rfloordiv__/
__rmod__/__rpow__(scalar)` when the right operand is a class that defines it (`2 * s`,
`1 - s`). CPython agrees natively: `@dataclass` keeps a user-defined `__eq__`, and Python's
own reflected-operator protocol picks the `__r*__` method.

**Ridden along.** `x is None` / `is not None` on a `PyVal` operand is a kind check
(`pyval_type_name(v) == "NoneType"`) in both backends — it used to emit `Option` code
(`.is_some()` on `PVal` in Backend A; a wrong GEP in Backend B). Backend A now evaluates the
value of `xs.append(v)` / `xs.insert(i, v)` in a block before taking the `&mut` receiver, so
`xs.append(len(xs))` compiles. Accept test: `tests/accept/097_pyval_none_reflected_eq.py`.

## D40 — `@overload`-typed `__getitem__`: the call site takes the overload's return type (2026-09-06)

**Decision.** A class body may carry `typing.overload` stubs for `__getitem__` followed by one
undecorated implementation whose key parameter is a union and whose return type is a union of
the stubs' return types:

```python
@overload
def __getitem__(self: Ref[DataFrame], key: str) -> Series: ...
@overload
def __getitem__(self: Ref[DataFrame], key: Ref[Series]) -> DataFrame: ...
def __getitem__(self: Ref[DataFrame], key: Ref[str | list[str] | Series]) -> Series | DataFrame: ...
```

The frontend strips the stubs from the body (they are never emitted); the checker keeps their
signatures on `ClassInfo.overloads` and, at each `obj[key]`, picks the first stub whose key type
accepts the argument type and gives the expression **that stub's return type** — the
implementation still returns the union, and each backend extracts the picked member at the
call site (Backend A `into_i()`, Backend B a GEP into the union temp; a moved-out member
consumes the temp so nothing is dropped twice). No stub matching → the union, as before.
Under CPython the same source runs unchanged (`typing.overload` stubs are ignored, the
implementation dispatches with `isinstance`). Only `__getitem__` is wired today; the mechanism
is method-agnostic and can be widened. Accept test: `tests/accept/098_getitem_overloads.py`.

**Why.** `df["a"]` → `Series`, `df[["a", "b"]]` / `df[mask]` → `DataFrame`, `df.loc[label]`
→ row `Series`, `df.loc[mask]` → `DataFrame`, `df.iloc[[0, 2]]` → `DataFrame`: the return type of
pandas' indexers depends on the key's *type*, which is exactly what static overloads express.

## D41 — Module-level object bindings and `@registrar` route decorators (2026-09-07)

**Decision.** A module may bind an object at module level, `app = FastAPI(...)` (or
`app: FastAPI = FastAPI(...)`), when the initializer is a call to a class. The binding is
**not a runtime global**: the frontend lowers it to a factory `_serp_app_<name>() -> C` and
rewrites every load of the name inside function bodies into a call to that factory, so each
use gets a fresh, fully-registered instance (`TestClient(app)`, `run(app)`). Mutating the
object through the module-level name outside decorators therefore does not persist —
build it in a function if you need that.

A class method marked `@registrar` (`from serpentine import registrar`) turns
`@X.m(args..., kw=...)` on a module function `f` into the registration call
`X.m(args..., <endpoint>, kw=...)` inside the factory, in source order. The registrar must
take an `endpoint: Callable[[Rq], Rs]` parameter; `<endpoint>` is `f` itself when `f` is
already `(x: Owned[Rq]) -> Rs`, otherwise a synthesized `_serp_ep_f(_serp_rq: Owned[Rq]) -> Rs`
that pulls each parameter out of the request by a fixed convention on `Rq`:

| handler parameter | synthesized extraction |
|---|---|
| `p: int/str/float/bool`, `{p}` in the decorator's path literal | `_serp_rq._serp_path_<kind>("p")` |
| `p: int/str/float/bool` (default `d` optional) | `_serp_rq._serp_query_<kind>("p", d-or-zero, has_default)` |
| `p: T \| None` / `Optional[T]`, scalar T | `_serp_rq._serp_query_opt_<kind>("p")` |
| `p: M` for a class with `model_validate_json[_errors]` (serp_molt) | `M.model_validate_json_errors(_serp_rq._serp_body())` → `_serp_rq._serp_validation_error(move(errs))` on failure, else `M.model_validate_json(...)`; the handler's annotation becomes `Owned[M]` and the value is `move`d in |

The return value goes through `_serp_rq._serp_respond_json(v)` unless the handler already
returns `Rs`; a model return becomes `v.model_dump()` (`fields_of(v)` for plain dataclasses),
`list[M]` a comprehension of the same, `None` → `_serp_respond_json(None)`. Anything else is
SE201.

Two more forms ride on the factory: a **module-level statement** `X.m(args...)` (e.g.
`app.add_api_route("/x", h, ["GET"])`, `app.include_router(router, prefix="/v1")`) is emitted
into `_serp_app_X` in source order together with the decorators, so several bindings compose
(`router = APIRouter(...)` is itself a binding whose name becomes a factory call inside the
app's factory); and a handler parameter defaulted to **`Depends(g)`** recurses: `g`'s own
parameters are injected by the same rules (locals prefixed `_serp_d_<g>_`), `g` is called, and
its result is bound (moved when non-Copy). A handler with any `Depends` loses its defaults —
the shim passes every argument positionally.

Under CPython the module-level binding and the decorators run as ordinary Python; the
shim's `registrar` wrapper returns a decorator that builds the identical endpoint dynamically
from `inspect.signature`/`get_type_hints` (recursing into `Depends`, and treating a call with a
callable positional as the direct native form). Accept test `099`, reject `r092`/`r093`.

Alongside: **empty `[]`/`{}` parameter defaults** on `Owned` list/dict parameters. The checker
keeps the literal as the default and materializes omitted trailing arguments at the call site
(backends still only render constant defaults), so `client.get(url, params={...})` and
`JSONResponse(v, headers={})` read like FastAPI/httpx.

**Why.** LB1 (module-level non-Copy constants) and LB2 (build-time signature introspection +
generated call shims) were the two items that made Venom "FastAPI-shaped" rather than
FastAPI. A true mutable global would need thread-safe lazy initialization and borrow rules in
both backends; a build-time factory needs neither, and a route table is exactly the kind of
object whose only mutation is registration. The convention-method design keeps the compiler
framework-agnostic — it knows `@registrar` and the `_serp_*` names, not FastAPI — so any
registry-shaped library (CLI command groups, event buses) can use the same mechanism.

## D42 — Exception classes with an `__init__` message builder (2026-09-07)

**Decision.** A user exception class may define exactly one method:

```python
class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        super().__init__(str(status_code) + ": " + detail)
```

The frontend lifts the message expression into a module function
`_serp_exmsg_<E>(<params>) -> str` and rewrites every constructor call `E(args..., kw=...)`
(in the defining module and in importers) into `E(_serp_exmsg_E(args..., kw=...))`, so kwargs,
defaults and typing all come from the ordinary function path. Exceptions remain single-message
values at runtime. The body may also assign `self.<x> = ...` before the `super()` call; each
such attribute is readable inside `except E as e:` as `e.<x>`, which the frontend rewrites to
`_serp_exattr_<E>_<x>(str(e))` — a module-level getter the defining library provides (it owns
the message format, so it owns the inverse: `HTTPException` decodes `"404: detail"` back into
`status_code`/`detail`). Under CPython the attributes are real. Any other `__init__` shape
(other statements, `*args`) is SE201. Accept `099`, reject `r094`.

## D43 — Tuple and slice subscript keys, the builtin `slice` class, tuple destructuring in for-loops (2026-09-07)

**Decision.** On a class value, `x[a, b]` desugars to `x.__getitem__(a, b)` (one positional
argument per tuple element) **when the dunder declares more than one key parameter**; a
single-key `__getitem__(self, key: tuple[int, int])` still receives the tuple as one value
(Coil's `m[i, j]`). `x[a:b:c]` desugars to `x.__getitem__(slice(a, b, c))`, with missing
bounds passed as `None`; both forms also drive `__setitem__` (`x[a, b] = v` →
`x.__setitem__(a, b, v)`). `slice` is a compiler-provided dataclass
(`compiler/src/serpentine_lang/_serp_builtins.py`, fields `start/stop/step: PyVal`) that the
frontend loads as the hidden module `_serp_builtins` and makes visible in every module that
does not define or import its own `slice`; under CPython the same code sees the real builtin
`slice` object, which has the same three attributes. D40 overload narrowing now matches stubs
of any arity, so `df.loc[mask, "col"]` and `df.loc[mask, ["a", "b"]]` can return different
static types. The shim's `dataclass` splats a tuple key into the extra positional parameters
of a multi-parameter `__getitem__`/`__setitem__` so the two worlds agree.

`for a, b in it:` over a user iterator whose `__next__` yields a tuple with non-Copy elements
is now accepted: the lowered `a = _t[0]; b = _t[1]` assignments are marked as destructures, each
element is *moved* out of the dead tuple temp (rustgen: partial move `v_t.1`; llvmgen: the
existing move-and-zero `_read_place`), and the Rc-handle drops (`rt_pyval_drop`,
`rt_bytes_drop`) tolerate a zeroed slot so the partially-moved temp drops cleanly. Accept `100`.

**Why.** `df.loc[mask, "col"]`, `df.iloc[2:5]` and `for i, row in df.iterrows()` are the
three pandas spellings every script uses; without them Scales could not be called a drop-in.
A builtin class instead of a new `TSlice` type reuses the whole dataclass pipeline (layout,
drops, isinstance narrowing) for the price of one hidden module.

## D44 — `PyVal` dicts carry `PyVal` keys (2026-09-07)

**Decision.** The runtime dict inside a `PyVal` is `SerpDict<PVal, PVal>` (was
`SerpDict<SStr, PVal>`); key equality is Python's (`1 == 1.0 == True`, strings by value), so
`d[1]`, `1.0 in d`, iteration and `repr` behave like CPython. A dict literal in a `PyVal`
position may use `int`, `float`, `bool` or `str` keys, but all keys of one literal must share a
type (mixed-key literals stay SE214); a typed `dict[int|float|bool|str, T]` coerces into a
`PyVal` like `dict[str, T]` did. JSON output coerces non-str keys the way CPython's `json` does
(`{1: 2}` → `{"1": 2}`, `True` → `"true"`, `None` → `"null"`). Accept `101`.

**Why.** `s.replace({1: "a"})`, `rename(index={0: "x"})` and `Series({1: "a"})` all need int
keys in a dynamic dict; str-only keys were an implementation shortcut, not a language rule.

## D45 — Baton-scheduled tasks: `await` suspends, `asyncio` is a drop-in (2026-09-07)

**Supersedes the eager half of D14.** `async def` still compiles to a plain function and
`await f(...)` on a coroutine still runs the call inline (same task, CPython's depth-first
order), but the program may now have many runnable tasks:

- **Tasks are OS threads that pass a baton.** `asyncio.create_task(f(a, b))` (the
  `_serp_create_task` intrinsic, Send-checked exactly like `spawn`) starts a thread that
  waits for the baton; exactly one task runs at any instant, and it hands the baton over
  when it suspends (`await task`, `asyncio.sleep`, an `Event`/`Lock`/`Queue` wait, or a
  socket would-block in async mode). Because there is never parallelism, `Rc`-based values
  are safe inside tasks and `PyVal`s can be queued.
- **Scheduling replays CPython's `_run_once`** — a FIFO ready queue drained in batches, then
  one readiness pass that queues I/O-ready tasks first (registration order) and expired
  timers second (`(when, seq)` order). Task completion, `Event.set`, `Lock.release`,
  `Queue.put/get` and `create_task` all append to the ready queue where CPython would
  `call_soon`, so dual runs interleave byte-identically (tests keep sleeps ≥ 20 ms apart:
  Windows CPython's timer resolution is 15.6 ms).
- **Surface.** Language-level: `asyncio.run`, `asyncio.sleep`, `asyncio.create_task`
  (`name=` accepted and dropped), `asyncio.gather(...)` (must be the whole RHS of an
  assignment/return or a bare statement; spread into task temporaries; results must share
  one type), `asyncio.Task[T]` with `await t` / `t.done()`, `asyncio.TimeoutError` = builtin,
  `async with` (`__aenter__`/`__aexit__`, same shape rules as `with`). Every other
  `asyncio.X` resolves to `serp_asyncio.X` (the `serp-asyncio` package: `Event`, `Lock`,
  `Semaphore`, `BoundedSemaphore`, `Queue`, `QueueEmpty`, `QueueFull` — runtime-held
  handles, so they are scalar classes that cross into tasks by copy). Async functions may
  be used as values and awaited through `Callable`s; a direct call to an async function
  that is not awaited/wrapped stays SE201.
- **Not supported:** `cancel()`/`CancelledError`, `Task.result()`, `wait_for`/`timeout`,
  `async for`, `gather(*coros)`, mixed-type gather, awaiting a task twice, more than one
  event loop per process (a second `asyncio.run` reuses the loop; leftover tasks are
  abandoned rather than cancelled).
- **Reactor.** Sockets have an *async mode* (`_serp_socket.set_async`): non-blocking, and a
  would-block parks the task on the fd (POLLIN/POLLOUT via the same WSAPoll/poll path as
  Venom's `poll_ready`) instead of blocking the thread; `set_timeout` becomes the reactor
  deadline. The plain `recv/send/send_all/accept` API is unchanged, so Fang's engine
  became cooperative without a second transport (`AsyncClient`), and Venom serves
  task-per-connection (`accept_async` + `serve_conn`, `async def` handlers awaited in
  `_handle_async`). Under CPython `set_async` is a no-op — network I/O there blocks the
  loop; results match, interleavings need not.
- **`block_on(x)`** (shim): identity natively (the frontend erases it); under CPython it runs
  a coroutine to completion when no loop is running, which is how synchronous dispatch
  (`TestClient`, `serve_on`) calls `async def` handlers. Registrars receive `is_async=True`
  for `async def` endpoints (frontend keyword + shim `iscoroutinefunction`).

Accept `102`, reject `r095`, lib suites `serp-asyncio`, `test_async_fang`, `test_async_venom`.
Native evidence: four 300 ms requests through `AsyncClient` complete in 0.30 s.

