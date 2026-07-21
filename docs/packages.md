# Multi-Package Design — Modules, Libraries, and Cross-Library Conventions

> **Status: implemented (v0.4)** — dotted imports, `serp.toml` discovery, declared
> roots, and dependency-gated venv resolution ship in `serp`; `serp init` / `serp new`
> scaffold projects and `serp add` / `serp remove` manage pinned PyPI dependencies
> (recorded in `serp.lock`). Sections below are the design of record; §2 notes the
> shipped semantics.

## 1. Where we are (v0.3)

`serp build main.py` loads `main.py` plus every `import name` / `from name import x`
that resolves to `name.py` **in the same directory**. Everything else is refused at the
interop boundary (`SE213`, `docs/interop.md`). Compilation is whole-program: one Rust
translation unit, monomorphization sees every call site.

## 2. Package layout (design)

A Serpentine *package* is a directory with an `__init__.py`-free, flat namespace —
deliberately simpler than CPython packages:

```
myproject/
  main.py            # entry
  util/
    text.py          # import util.text  →  util/text.py
    fmt.py
  serp.toml          # optional manifest (deps, name, version)
```

- `import util.text` resolves to `<root>/util/text.py`; the module name is the full
  dotted path. **Shipped form: `from util.text import name` (any nesting depth);
  plain `import util.text` with attribute access stays out (only `import sys` is
  special-cased).** Relative imports are refused (SE213).
- No package-level `__init__.py` execution — imports stay side-effect-free (SPEC §9's
  "import has no side effects" rule scales as-is). Under CPython the directories
  resolve as namespace packages.
- Resolution order (shipped): (1) entry-file directory tree, (2) `[build] roots`
  declared in `serp.toml` (found by walking up from the entry file), (3) the project
  venv's site-packages, gated to distributions listed under `[dependencies]`,
  (4) refuse (`SE213`). CPython sees the same files via ordinary `sys.path` semantics,
  preserving dual execution — venv dependencies are on `sys.path` automatically;
  extra `[build] roots` need `PYTHONPATH` (or a `.pth` file) for the CPython run.
- Two module names that mangle to the same generated identifier (`util.text` vs
  `util_text`) are refused at load time.

### 2.1 serp.toml (shipped schema)

```toml
[project]
name = "myproject"
version = "0.1.0"

[dependencies]          # written by `serp add`, exact pins
mylib = "==1.2.0"

[build]
roots = ["vendor"]      # optional extra import roots, relative to serp.toml
```

`serp.lock` (written by `serp add`) records name, version, sha256, and wheel
filename per dependency for reproducible installs.

## 3. Libraries ship as source

Whole-program compilation is the load-bearing decision: **a Serpentine library is a
source distribution** (a normal PyPI sdist/wheel of `.py` files with the shim as its
only dependency). Consumers compile it together with their program.

Why source, not compiled artifacts:

1. **Monomorphization needs bodies.** Generic functions/classes and protocol-bounded
   APIs instantiate per concrete type at the *consumer's* call sites. Shipping compiled
   rlibs would require a stable generic ABI — the exact rabbit hole C++/Rust solve with
   header/source and crate compilation; we take the same answer as Rust crates: compile
   from source, cache aggressively.
2. **Dual execution comes free.** The same wheel is importable by CPython (it is just
   Python) and compilable by `serp`. One artifact, both worlds.
3. **rustc-as-oracle keeps working** across library boundaries — the generated program
   is still one Rust crate.

Build cost is managed by (a) per-module Rust codegen caching keyed on source hash +
compiler version, and (b) the fact that Tier-2 programs are small. A `serp.lock` records
resolved library versions for reproducible builds.

## 4. Cross-library API conventions (normative once packages land)

Public functions and methods of a library must state ownership explicitly — the same
rules as today, hardened into API guidelines:

- **Parameters:** `Ref[T]` for read access, `Mut[T]` for in-place mutation, `Owned[T]`
  only when the library genuinely stores or consumes the value. Copy types stay plain.
  Taking `Owned` "just in case" is an API bug: it forces `move()` on every caller.
- **Returns are always owned values** (returned borrows stay forbidden across library
  boundaries even if a future tier adds local elision — a library API that returns a
  borrow couples the caller to the callee's internals).
- **Generics:** exported generic functions/classes must bound their type variables with
  protocols when they call methods on `T` — an unbounded `T` is opaque. Instantiation
  happens in the consumer's build; the bound is the contract that makes cross-package
  monomorphization checkable at the declaration site rather than as post-hoc template
  errors.
- **Protocols are the interface vocabulary** between libraries (structural, so no shared
  base-class package is ever needed).
- **Errors:** libraries raise the built-in exception classes; user-defined exception
  classes are a Tier-3 item and until then `ValueError(msg)` with a documented message
  prefix is the convention.
- **No mutable module state** (already enforced: SE206) — libraries are functions,
  classes, and Copy constants, which is exactly what makes linking two libraries into
  one program safe without an init-order story.
- **Naming:** a library's modules live under one top-level directory named after the
  distribution (`import mylib.parse`), so the flat single-directory namespace of the
  consumer's own code never collides with dependencies.

## 5. Non-goals

- Separate/incremental *native* compilation of libraries (revisit if build times demand).
- A Serpentine-specific package registry: PyPI is the registry; `serpentine-shim` is the
  marker dependency; `serp.toml` only maps import roots.
- Cross-version generic ABI stability — irrelevant under source distribution.
