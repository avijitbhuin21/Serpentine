# CPython Interop Boundary (../archive/research.md §5.12)

> Phase-4 design + implementation record. The question: what happens when a Serpentine
> program imports something that is not a Serpentine module — can native binaries call
> into CPython for unported libraries, and if so, who owns the objects that cross?

## The three candidate designs

### A. Embed libpython, deep-copy at the boundary

The native binary links `libpython3.x`, foreign calls run in an embedded interpreter,
and every value crossing the boundary is **converted by deep copy**:

- Serpentine → CPython: build a fresh `PyObject` tree from the native value (ints/floats/
  bools/str are direct; lists/dicts/tuples recurse; dataclass instances become dicts or
  ad-hoc objects). Ownership is unaffected — the callee gets a snapshot, the native value
  never escapes.
- CPython → Serpentine: the returned `PyObject` is converted into a fresh **owned** native
  value against a declared expected type; conversion failure is a fatal `TypeError`.
  The `PyObject` refcount is released immediately after conversion — no live references
  are retained, so the GC stays fully contained inside the boundary.
- Only Tier-0 data types may cross. `Shared`, `Weak`, open files, and class instances
  containing them are rejected at check time. No callbacks (a CPython callee can never
  call back into native code in v1 of this design).

This preserves both the ownership model (nothing aliases across the boundary) and the
Dual-Execution Guarantee (under CPython the "boundary" is the identity function). Its
costs: a libpython link dependency (kills the zero-dependency static binary — the
headline Phase-3 result), a deployment-time interpreter version pin, deep-copy cost per
call, and a large implementation surface (PyObject marshalling for every Tier type).

### B. Reimplement a curated stdlib subset natively

No interpreter in the binary; `import math`-style modules are re-implemented in the
runtime with CPython-parity semantics, tier by tier, driven by corpus demand.
This is not interop — it is surface growth — but it is what actually unblocks most
small tools (`math`, `json`, `os.path` slices). It keeps static binaries static.

### C. Refuse (status quo, made explicit)

Foreign imports are a check-time error. The only supported way to use an unported
library is to run the whole program under CPython — which every Serpentine program
already supports by construction.

## Decision (D6)

**v0.1 ships C (refuse), with A (deep-copy) as the specified design for when demand
arrives, and B as the preferred pressure valve for specific high-demand modules.**

Rationale, in order:

1. **The static binary is the product.** Phase 3's headline is a 136 KB binary with zero
   libpython references. Design A un-ships that for every program that touches the
   boundary; it must stay opt-in and off by default. Nothing in the corpus study needs it.
2. **Dual execution already covers development.** The CPython side of every Serpentine
   program runs the full ecosystem today (you can profile with `cProfile`, debug with
   `pdb`, test with `pytest` — around the program, not inside it). What is lost is only
   foreign calls *inside deployed native binaries* — the rarest case for small tools.
3. **Deep-copy is the only sound ownership answer** if/when A lands: reference-semantics
   sharing across the boundary would alias GC-managed and ownership-managed memory, which
   is exactly the class of bug this language exists to remove. That part of the design is
   settled now, so implementing A later cannot warp the ownership model.

## What is implemented

- `SE213 foreign-import` is the boundary. The diagnostic now states the policy and points
  here. Only `import sys` (argv/exit) and `from serpentine import ...` (the shim) cross.
- The shim direction of the boundary — running the whole program under CPython — is the
  supported interop path and is exercised by the entire differential test suite.
- The divergence surface is zero: a program either checks (and behaves identically on
  both sides) or it does not compile natively.

## Non-goals for v0.1

- No `# serp: interop` escape comments; no per-function libpython opt-in. One program,
  one execution model.
- No FFI to C. That is a different feature (and a smaller ownership problem than
  libpython, since C has no GC — likely lands before A does).
