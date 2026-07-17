# Serpentine — Master Checklist

> Work top to bottom. Every box checked = project done. Details for each item live in RESEARCH.md (§ refs inline).

## Phase 0 — Spec & Foundations

- [ ] Register `serpentine-lang` + `serpentine-shim` on PyPI and grab the GitHub org (§6.11) — *names verified free 2026-07-17; package is publish-ready; needs owner credentials*
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

- [ ] Scaffold the `serp` CLI with `check` and `build` subcommands (§4)
- [ ] Frontend: `ast` parsing, module discovery, three-bin import resolution (§3.10)
- [ ] Name resolution / symbol tables
- [ ] Type checker: full-annotation enforcement over Tier-0 types (§4.②)
- [ ] Flow-sensitive `is None` narrowing in the type checker (§3.6)
- [ ] Design SIR: CFG, basic blocks, places, explicit move/borrow/drop ops (§4.③)
- [ ] AST → SIR lowering for the minimal language (ints, functions, if/while, lists)
- [ ] Initialized-places dataflow analysis (§4.④)
- [ ] Lexical loan analysis: any number of `Ref` XOR one `Mut` (§3.2)
- [ ] Drop insertion at end of lexical scope (§3.2)
- [ ] Diagnostics v1: error codes, source spans, primary labels
- [ ] Backend A: SIR → Rust codegen incl. floor-div/mod helpers (§4.⑤a, §7)
- [ ] Runtime-error parity in generated Rust (CPython messages, exit 1) (§3.9)
- [ ] `serp build`: invoke rustc, emit the native binary
- [ ] Differential test harness: every accept test runs CPython + native, stdout diffed (§5.6)
- [ ] **Milestone: fib.py + a list program dual-run with byte-identical output (§9)**

## Phase 2 — Make the Checker Real

- [ ] Field-sensitive tracking: partial moves, `x.f` moved while `x.g` live (§5.7)
- [ ] Fixed-point dataflow for loops (move-in-loop-body cases) (§6.3)
- [ ] Iterator-invalidation rule: `for` holds a `Ref` of the iterable for the body (§6.6)
- [ ] `Shared[T]` + `Weak[T]`: refcounted escape hatch, leak-on-cycle policy (§8.2)
- [ ] Tier-1 classes: `@dataclass`-style fields + methods, no inheritance (§3.1)
- [ ] Generics with monomorphization on functions and classes (§3.1)
- [ ] Exceptions: try-as-sub-scope borrows, unwind-path drops, catchable runtime errors (§8.1, §3.9)
- [ ] Tier-1 builtins: `open()` with drop-closes-file, `sys.argv`, `sys.exit` (§3.8)
- [ ] Error UX pass: secondary "moved here" labels, suggested fixes, rustc-quality polish (§5.8)
- [ ] rustc-agreement harness: transpile corpus, diff verdicts, fix every disagreement (§4)
- [ ] Corpus study: run checker on real small programs, catalog rejected idioms (§5.9)
- [ ] **Milestone: all reject tests caught with quality messages; checker agrees with rustc (§9)**

## Phase 3 — Native Backend & Benchmarks

- [ ] Runtime library: malloc/free wrappers, `Rc<str>` strings, list, insertion-ordered dict (§3.7, §5.10)
- [ ] Runtime: Ryū/grisu float repr + container repr parity with CPython (§7)
- [ ] Runtime: error values (not aborts) so exceptions stay cheap to support (§3.9)
- [ ] Backend B: SIR → LLVM IR (llvmlite or inkwell) (§4.⑤b)
- [ ] Static binary with zero libpython dependency (§9)
- [ ] Benchmark suite vs CPython / Codon / mypyc / handwritten Rust (§5.11)
- [ ] Allocation-heavy benchmark demonstrating the no-GC dividend over Codon (§5.11)
- [ ] **Milestone: Codon-class numeric perf, better on allocation-heavy workloads (§9)**

## Phase 4 — Ecosystem & Release

- [ ] Design + implement the CPython interop boundary (deep-copy or refuse) (§5.12)
- [ ] Tier-2 features in demand order from corpus data: closures, protocols, iterators, `with` (§3.1)
- [ ] Refactor checker-as-library, ship LSP for editor diagnostics (§5.13)
- [ ] North-star demo: JSON parser developed under CPython, deployed as native binary (§9)
- [ ] Docs: language tour, ownership guide, divergence page, migration notes
- [ ] Publish `serpentine-lang` v0.1 + announce
