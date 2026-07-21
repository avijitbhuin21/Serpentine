# Serpentine — Master Checklist

> Work top to bottom. Every box checked = project done. Details for each item live in RESEARCH.md (§ refs inline).

## Phase 0 — Spec & Foundations

- [x] Register `serpentine-lang` + `serpentine-shim` on PyPI and grab the GitHub org (§6.11) — *published 2026-07-20 via trusted publishing (repo `avijitbhuin21/Serpentine`, `release.yml` on `v*` tags)*
- [x] Init repo: license, README, `.gitignore`, CI skeleton pinned to CPython 3.12 (§4 version pin)
- [x] Write `SPEC.md`: Tier-0 grammar (types, statements, expressions) (§3.1)
- [x] Spec ownership rules as judgments (move, borrow, drop, Copy types) (§3.2)
- [x] Spec call-site conventions incl. builtin method receiver rules (§3.4)
- [x] Spec places & element-access rules (no move-out-by-index, `for` variable semantics) (§3.5)
- [x] Spec `Optional[T]` narrowing rules (§3.6)
- [x] Spec the Tier-0 builtins surface (functions, str/list/dict methods, f-strings) (§3.8)
- [x] Spec the fatal-runtime-error model (error classes, messages, exit code) (§3.9)
- [x] Spec modules, imports (three bins), module-level code rules, entry point (§3.10)
- [x] Spec the divergence list (int64+trap, floor-div, bool arithmetic, repr parity, tracebacks) (§7)
- [x] Paper-prototype exceptions × ownership (try sub-scope proposal) (§8.1) — `docs/exceptions-ownership.md`
- [x] Decide remaining §8 questions: `Shared` cycles, returned borrows, threading posture — `DECISIONS.md`
- [x] Hand-write 30–50 `tests/accept/` programs (§5.2) — 36, all run clean under CPython
- [x] Hand-write 30–50 `tests/reject/` programs, each annotated with its exact expected error (§5.2) — 37
- [x] Ship `serpentine-shim` v0.1: `Owned`/`Ref`/`Mut`/`Shared`/`Weak`/`move` as no-ops (§5.3) — built + validated; PyPI upload pending credentials

## Phase 1 — Walking Skeleton

- [x] Scaffold the `serp` CLI with `check` and `build` subcommands (§4) — `compiler/`, installable, `serp` entry point
- [x] Frontend: `ast` parsing, module discovery, three-bin import resolution (§3.10)
- [x] Name resolution / symbol tables
- [x] Type checker: full-annotation enforcement over Tier-0 types (§4.②)
- [x] Flow-sensitive `is None` narrowing in the type checker (§3.6)
- [x] Design SIR: CFG, basic blocks, places, explicit move/borrow/drop ops (§4.③) — `serp check --dump-sir`
- [x] AST → SIR lowering for the minimal language (ints, functions, if/while, lists)
- [x] Initialized-places dataflow analysis (§4.④) — worklist fixed point; loop moves caught
- [x] Lexical loan analysis: any number of `Ref` XOR one `Mut` (§3.2) — for-loop regions + intra-call conflicts
- [x] Drop insertion at end of lexical scope (§3.2) — drop ops in SIR at scope exits
- [x] Diagnostics v1: error codes, source spans, primary labels
- [x] Backend A: SIR → Rust codegen incl. floor-div/mod helpers (§4.⑤a, §7) — *codegen emits structured Rust from the typed AST; SIR drives the analyses (keeps rustc-as-oracle meaningful)*
- [x] Runtime-error parity in generated Rust (CPython messages, exit 1) (§3.9)
- [x] `serp build`: invoke rustc, emit the native binary
- [x] Differential test harness: every accept test runs CPython + native, stdout diffed (§5.6) — `tools/run_differential_tests.py`, 36/36
- [x] **Milestone: fib.py + a list program dual-run with byte-identical output (§9)** — entire accept corpus dual-runs identically

## Phase 2 — Make the Checker Real

- [x] Field-sensitive tracking: partial moves, `x.f` moved while `x.g` live (§5.7) — one-level place sensitivity in borrowck; SE008 for moves out of borrows
- [x] Fixed-point dataflow for loops (move-in-loop-body cases) (§6.3) — *landed in Phase 1 (worklist fixed point); re-verified*
- [x] Iterator-invalidation rule: `for` holds a `Ref` of the iterable for the body (§6.6) — *landed in Phase 1 (loan regions); Phase 2 added the no-mutation-through-loop-Ref rule*
- [x] `Shared[T]` + `Weak[T]`: refcounted escape hatch, leak-on-cycle policy (§8.2) — `share`/`downgrade`/`upgrade`, Rc<RefCell> backend, runtime-borrow errors
- [x] Tier-1 classes: `@dataclass`-style fields + methods, no inheritance (§3.1) — Ref/Mut self conventions, dataclass repr/eq parity, by-value-cycle rejection
- [x] Generics with monomorphization on functions and classes (§3.1) — TypeVar + Generic[T], AST-copy instantiation per argument types
- [x] Exceptions: try-as-sub-scope borrows, unwind-path drops, catchable runtime errors (§8.1, §3.9) — E1 join in borrowck; runtime rebuilt on SerpErr error values; labeled-block Rust lowering
- [x] Tier-1 builtins: `open()` with drop-closes-file, `sys.argv`, `sys.exit` (§3.8)
- [x] Error UX pass: secondary "moved here" labels, suggested fixes, rustc-quality polish (§5.8) — secondary spans + `help:` lines in diagnostics
- [x] rustc-agreement harness: transpile corpus, diff verdicts, fix every disagreement (§4) — `tools/run_rustc_agreement.py`: 11 confirmed, 11 policy-only, 0 disagreements
- [x] Corpus study: run checker on real small programs, catalog rejected idioms (§5.9) — `docs/corpus-study.md`
- [x] **Milestone: all reject tests caught with quality messages; checker agrees with rustc (§9)** — 50/50 rejects exact codes; 48/48 accept tests dual-run byte-identical

## Phase 3 — Native Backend & Benchmarks

- [x] Runtime library: malloc/free wrappers, `Rc<str>` strings, list, insertion-ordered dict (§3.7, §5.10) — runtime = `prelude.rs` (Rust std allocator, Vec, SerpDict); strings converted to `Rc<str>` (O(1) copies); range() made a lazy iterator
- [x] Runtime: Ryū/grisu float repr + container repr parity with CPython (§7) — Rust's shortest-roundtrip `{:?}` + exponent normalization; locked in by `tests/accept/049_repr_parity.py`
- [x] Runtime: error values (not aborts) so exceptions stay cheap to support (§3.9) — *landed in Phase 2 (SerpErr / SRes<T>); re-verified*
- [x] Backend B: SIR → LLVM IR (llvmlite or inkwell) (§4.⑤b) — `llvmgen.py` emits LLVM IR from the typed AST (same deliberate deviation as Backend A) for the numeric core; `serp llvm` JIT-runs it; `tools/run_llvm_differential.py` byte-compares vs CPython
- [x] Static binary with zero libpython dependency (§9) — 136 KB fib binary, zero `python3*` DLL references, runs with an empty PATH
- [x] Benchmark suite vs CPython / Codon / mypyc / handwritten Rust (§5.11) — `benchmarks/` + `tools/run_benchmarks.py`; Codon (no Windows support) and mypyc (no cl.exe) not runnable on this host, documented in `docs/benchmarks.md`
- [x] Allocation-heavy benchmark demonstrating the no-GC dividend over Codon (§5.11) — `bench_alloc.py`: 8.8x vs CPython, parity with handwritten Rust; head-to-head vs Codon deferred to a Linux host
- [x] **Milestone: Codon-class numeric perf, better on allocation-heavy workloads (§9)** — 36x (fib) / 143x (floats) over CPython; alloc churn at handwritten-Rust parity — see `docs/benchmarks.md` (strings are a documented 0.6x gap)

## Phase 4 — Ecosystem & Release

- [x] Design + implement the CPython interop boundary (deep-copy or refuse) (§5.12) — `docs/interop.md` + DECISIONS.md D6: v0.1 refuses (SE213 states the policy); deep-copy boundary fully specified for when demand arrives
- [x] Tier-2 features in demand order from corpus data: closures, protocols, iterators, `with` (§3.1) — shipped: comprehensions, str index/slice, `sorted` (+`key=` lambda closures), `with open`, default params, `zip`/`reversed`/str iteration, `round`/`ord`/`chr`, structural protocols as generic bounds (SE215); user-defined `__iter__`/`__next__` deferred by D7 (stored borrows; zero corpus demand); SPEC.md §14
- [x] Refactor checker-as-library, ship LSP for editor diagnostics (§5.13) — `serpentine_lang.api` (check_file/check_source with buffer overlays) + `serp lsp` (stdio, dependency-free); `tools/run_lsp_smoke.py`
- [x] North-star demo: JSON parser developed under CPython, deployed as native binary (§9) — `examples/json_parser.py` (full escapes incl. surrogate pairs, error recovery); byte-identical dual-run; locked into the corpus as `tests/accept/055_json_roundtrip.py`
- [x] Docs: language tour, ownership guide, divergence page, migration notes — `docs/tour.md`, `docs/ownership.md`, `docs/divergences.md`, `docs/migration.md` (+ `docs/interop.md`)
- [x] Publish `serpentine-lang` v0.1 + announce — *published 2026-07-20: serpentine-lang 0.4.0 + serpentine-shim 0.3.0 live on PyPI (trusted publishing, tag `v0.4.0`); verified end-to-end (fresh venv, pip install, dual-run). Announcement still open — venues in `docs/publishing.md`*

## Bonus — Phase 4 backlog (readiness-report findings, 2026-07-17)

> Ordered by impact-per-effort from the post-Phase-3 readiness report and the corpus study
> (`docs/corpus-study.md`). Items feed into the Phase-4 boxes above.

### Daily-tool ergonomics (fastest path to "use it for local things")
- [x] List/dict comprehensions (top corpus rejection; desugars to loop + append, no ownership novelty) — *landed with Phase 4 (SPEC §14)*
- [x] String slicing `s[a:b]` (missing entirely — bites every text tool) — *landed with Phase 4 (+ `s[i]` indexing, str iteration)*
- [x] `sorted(xs)` keyless (no closures needed) — *landed with Phase 4, plus `key=lambda` (Copy elements)*
- [x] `with open(...) as f:` RAII sugar (Tier-2 §3.1, high demand) — *landed with Phase 4*
- [x] Default parameter values — *landed with Phase 4 (literal defaults, functions + methods)*
- [x] Small builtin gaps: `round()`, `str.format`-adjacent specs, more str/dict methods — *`round`/`ord`/`chr`/`zip`/`reversed` landed; `str.format` itself stays out (f-strings cover it); further str/dict methods by demand*
- [x] Named element borrows (scoped borrow of `rows[0]` — most-wanted ergonomic fix from the corpus study) — *landed 2026-07-18: `first = rows[0]` binds a block-scoped Ref; container frozen (SE004/SE005) while live; SPEC §14.1; tests/accept/057, tests/reject/r053*
- [x] `is None` narrowing on field places (currently plain names only) — *landed 2026-07-18: one-level `x.f` narrowing, invalidated by assignment/Mut use, never through Shared; tests/accept/056*

### Performance
- [x] String runtime optimization (0.6x CPython on transformation pipelines: ASCII byte-len fast path, buffer-reusing ops, SSO/arena — see `docs/benchmarks.md`) — *landed 2026-07-18: SSO (≤22 B inline, zero alloc) + ASCII fast paths → 0.8–1.0x CPython (was 0.6x; interleaved min-of-5 measures parity, harness median 0.8x); docs/benchmarks.md Phase-4 update*
- [ ] Re-run `bench_alloc.py` head-to-head vs Codon on a Linux/macOS host (Codon has no Windows support) — **host-blocked: this machine is Windows-only; needs owner action or a Linux/macOS box**

### Library-building prerequisites
- [x] Multi-package/module resolution design (imports are single-directory bin-1 only; libraries ship as source under whole-program compilation) — *design of record: `docs/packages.md` (package dirs, serp.toml roots, source-distribution libraries, build caching)*
- [x] Cross-library API conventions: ownership in public signatures, monomorphization across package boundaries — *`docs/packages.md` §4 (conventions normative once packages land)*
- [x] Protocols/traits + closures (blocking any real library API surface; Tier 2) — *structural protocols as generic bounds landed (SE215); closures landed as the `sorted key=` subset — general closures still open*
- [x] Iterators as first-class borrows (Tier 2) — *landed 2026-07-18: `it = iter(xs)` block-scoped borrow + `next(it)` + catchable StopIteration (Copy elements); tests/accept/058; DECISIONS.md Phase-4 backlog entry*

### Housekeeping
- [x] Bump CI actions (checkout@v4 / setup-python@v5) to silence Node-20 deprecation annotations — *bumped to checkout@v5 / setup-python@v6; LSP smoke test added to CI*
- [x] `Owned` (consuming) `self` methods (deferred from Phase 2, SE202) — *landed 2026-07-18: `move(x).method()` call discipline (SE002 without move, SE001 after); SPEC §14.1; tests/accept/058, tests/reject/r048*
- [x] Backend B: grow the LLVM numeric core (float printing via shortest-roundtrip, strings) or fold into Phase-4 priorities — *folded into Phase-4 priorities; Backend B stayed the numeric-core demo (`serp llvm`, harness green); now superseded by Phase 5 below*

## Phase 5 — Backend B grows up: direct-to-LLVM native builds

> Goal: `serp build` can skip the Rust round-trip entirely — SIR → LLVM IR → object → linked
> native binary — with a **debug mode** (minimal LLVM work, fast links) targeting 2–3x faster
> builds and a **release mode** (full optimization pipeline) matching Backend A's runtime perf.
> Backend A (Rust) stays as the reference backend and rustc-as-oracle for the borrow checker.

### 5.0 Design & runtime strategy
- [ ] Decision doc: runtime via `prelude.rs` compiled ONCE as a `staticlib` with a C ABI (reuse everything: SStr/SSO, Vec lists, SerpDict, Rc/Weak, SerpErr) vs. hand-written C runtime — record in `DECISIONS.md`
- [ ] Define the C ABI surface (`serp_rt.h` equivalent): naming, ownership transfer rules at the boundary, error-value returns (`SRes<T>` as out-param + status), panic-free guarantees
- [ ] Build + cache the runtime staticlib per compiler version/target (`%LOCALAPPDATA%/serp/rt/<ver>-<target>/serp_rt.lib`); rebuild only on prelude change
- [ ] Spec debug vs release semantics: identical program behavior, only compile-time/optimization differ (divergences doc gets a "none" entry)

### 5.1 Lowering: full language coverage in `llvmgen.py`
- [ ] Strings: SStr through the runtime ABI (construction, concat, methods, f-string formatting, repr parity incl. float shortest-roundtrip)
- [ ] Lists: literals, index/slice, methods (append/pop/extend/sort/…), iteration, element borrows
- [ ] Dicts: SerpDict ABI, literals, methods, insertion-order iteration, `in`
- [ ] Tuples + Copy semantics table parity with Backend A
- [ ] Tier-1 classes: struct layout, methods (Ref/Mut/Owned self), dataclass repr/eq parity, generics via monomorphized instantiations
- [ ] `Shared[T]`/`Weak[T]`: Rc/Weak ABI incl. runtime borrow-error parity
- [ ] Exceptions: error-value scheme (no unwinding/landing pads) — SRes checks + early-return blocks, try/except lowering, catchable runtime errors, CPython-parity messages + exit code 1
- [ ] Drops: scope-exit + unwind-path drop insertion mirrored from SIR drop ops
- [ ] Tier-1/2 builtins: `open()`/`with` (drop closes), `sys.argv`/`sys.exit`, comprehensions, `sorted` + `key=` closures, `zip`/`reversed`/`enumerate`/`range`, `round`/`ord`/`chr`
- [ ] Multi-module programs (same three-bin import rules as Backend A)

### 5.2 Emit, link, modes
- [ ] `serp build --backend llvm` (Backend A remains default until 5.3 exit criteria met)
- [ ] Object emission via llvmlite `emit_object`; link with the platform linker (link.exe / lld) against the runtime staticlib
- [ ] **Debug mode** (`--debug`): opt-level 0, no LLVM pass pipeline, fast link → measure and document the 2–3x build-time win vs Backend A `--debug`
- [ ] **Release mode**: full -O2/O3 + targeted passes; runtime perf within noise of Backend A on `benchmarks/`
- [ ] Debug info: source-line mapping (DWARF/PDB) so native stack traces point at `.py` lines
- [ ] Build-time benchmark harness: compile-time comparison A vs B (debug + release) on the corpus + a synthetic large program

### 5.3 Verification & exit criteria
- [ ] Extend `tools/run_llvm_differential.py` to the ENTIRE accept corpus: byte-identical stdout vs CPython (same bar as Backend A)
- [ ] All runtime-error accept/reject behaviors match (messages, exit codes)
- [ ] `benchmarks/` suite: Backend B release within 5% of Backend A across fib/floats/alloc/strings
- [ ] CI: LLVM-backend differential job (llvmlite install + full corpus) on all three OS runners
- [ ] **Milestone: whole corpus builds + dual-runs byte-identical through direct LLVM; debug builds ≥2x faster than Backend A debug; Backend A retained as oracle (§9)**
