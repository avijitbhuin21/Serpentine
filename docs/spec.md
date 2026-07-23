# Serpentine Language Specification — Tier 0

> **Spec-of-record for the compilable subset.** Changes to this file are spec changes and go
> through PR review, even with a single contributor. Details and rationale live in
> `archive/research.md`; where the two disagree, this file wins for Tier-0 behavior.

**Version:** 0.1 (Phase 0)
**Frontend pin:** CPython **3.12** — the grammar below is defined against the `ast` module of
CPython 3.12. Raising the pin is a deliberate spec change.

---

## 1. Scope

### 1.1 What Serpentine is

Serpentine compiles a statically typed, ownership-disciplined subset of Python to native code
with no garbage collector. The same source file runs unmodified under CPython (the
**Dual-Execution Guarantee**): any program accepted by `serp check` produces the same
observable behavior interpreted and compiled, modulo the divergence list in §10.

### 1.2 Tier boundaries

This document specifies **Tier 0** only. Tier-1/2 features (classes, exceptions, generics,
`Shared[T]`, closures, `with`, protocols) are out of scope here; using them is a checker error
`SE201 unsupported-feature`, not undefined behavior.

**Explicitly never supported (any tier):** `eval`/`exec`, monkeypatching, metaclasses, dynamic
attributes, runtime reflection, multiple inheritance, `globals()` mutation.

### 1.3 Conformance

- `serp check` MUST reject any program using a construct not listed in this spec.
- `serp check` MUST accept every program in `tests/accept/` and reject every program in
  `tests/reject/` with the error code annotated in the file. **The test corpus is part of the
  spec.**

---

## 2. Types

### 2.1 Tier-0 types

| Type | Kind | Copy? |
|---|---|---|
| `int` | 64-bit signed integer (§10 divergence) | yes |
| `float` | IEEE-754 double | yes |
| `bool` | true/false; **not** usable in arithmetic (§10) | yes |
| `str` | immutable text; native repr is a refcounted buffer (`Rc<str>`) | yes |
| `None` | unit; only as `T \| None` or a `-> None` return | yes |
| `list[T]` | owned growable sequence | no |
| `dict[K, V]` | owned insertion-ordered map; `K` must be Copy | no |
| `tuple[T1, ..., Tn]` | fixed-shape product | Copy iff every element is Copy |
| `T \| None` (= `Optional[T]`) | optional value; the only union (§6) | Copy iff `T` is Copy |

Ownership wrappers `Owned[T]`, `Ref[T]`, `Mut[T]` are **parameter/variable annotations**, not
types: they describe how a value is held, never what it is. `Owned[T]` may annotate parameters
and local variables; `Ref[T]`/`Mut[T]` may annotate **parameters only** (a `Ref`/`Mut` local
would be a stored borrow, J5). Any other position — nesting (`list[Ref[int]]`), returns,
container elements — is `SE202 invalid-wrapper-position`.

### 2.2 Copy vs non-Copy

Copy types have value semantics everywhere: assignment, argument passing, and returns copy;
`move()` on a Copy value is a no-op and a style warning, never an error. Non-Copy types (`list`,
`dict`, non-Copy `tuple`) obey the ownership rules of §4.

### 2.3 Annotation obligations

- Every function parameter and return type MUST be annotated (`SE203 missing-annotation`).
- A local binding MUST be annotated at its first initialization if its type is not the exact
  type of the right-hand side's inferred type... in Tier 0 the rule is simpler: locals MAY
  omit the annotation; the type is the RHS type. Annotating is required only where the RHS is
  an empty container literal (`[]`, `{}`), whose element type is otherwise unknown
  (`SE204 unknown-element-type`).
- There is **no global type inference.** Function signatures are the inference boundary.

---

## 3. Grammar (Tier 0)

Subset of the CPython 3.12 grammar. Anything not derivable below is `SE201`.

### 3.1 Module structure

```
module     := docstring? (import_stmt | funcdef | constdef | entry_guard)*
import_stmt:= "from" "serpentine" "import" names          # bin 2, erased (§9)
            | "import" serp_module | "from" serp_module "import" names   # bin 1
constdef   := NAME ":" copy_type "=" const_expr           # module-level Copy constant
entry_guard:= "if" "__name__" "==" '"__main__"' ":" call_stmt
funcdef    := "def" NAME "(" params ")" "->" type ":" docstring? block
docstring  := STRING                                      # ignored by check and build
```

Module-level statements other than these are `SE205 module-level-statement`. Mutable globals
are `SE206 mutable-global`.

### 3.2 Statements

```
stmt := assign | aug_assign | expr_stmt | if | while | for | return | pass | break | continue
assign     := target (":" annotation)? "=" expr          # target: NAME | place
aug_assign := place ("+=" | "-=" | "*=" | "/=" | "//=" | "%=") expr
if         := "if" expr ":" block ("elif" expr ":" block)* ("else" ":" block)?
while      := "while" expr ":" block
for        := "for" (NAME | NAME "," NAME) "in" expr ":" block   # 2-name form: enumerate/items only
return     := "return" expr?
```

Not in Tier 0: `try`/`raise` (Tier 1), `with` (Tier 2), `match`, `assert`, `del`, `global`,
`nonlocal`, `lambda`, `yield`, `async`, comprehensions, decorators (other than none),
starred/keyword-variadic parameters, default parameter values, walrus `:=`.

### 3.3 Expressions

```
expr := literal | NAME | place | call | binop | unaryop | boolop | compare
      | fstring | tuple_display | list_display | dict_display | ternary
place    := NAME ("[" expr "]")*                 # x, xs[i], grid[i][j]
call     := NAME "(" args ")" | expr "." NAME "(" args ")"
         # receiver may be any expr: places are borrowed per §7.1; a temporary
         # (literal, call result) is borrowed for the call and dropped after —
         # enables "-".join(xs) and s.strip().upper() chaining
binop    := expr ("+"|"-"|"*"|"/"|"//"|"%"|"**") expr
compare  := expr ("=="|"!="|"<"|"<="|">"|">=") expr
         | expr ("in"|"not in") expr             # dict/list membership
         | NAME "is" "None" | NAME "is not" "None"    # ONLY None-tests (§6)
boolop   := expr ("and"|"or") expr | "not" expr
ternary  := expr "if" expr "else" expr
```

- `is`/`is not` against anything but `None` is `SE207 identity-comparison` (§10).
- Chained comparisons (`a < b < c`) are accepted with CPython semantics.
- `bool` in an arithmetic position (`True + 1`, `sum` of bools) is `SE208 bool-arithmetic`;
  write `int(b)` (§10).
- Division `/` always yields `float`; `//` and `%` follow CPython floor semantics (§10).

---

## 4. Ownership Rules (judgments)

State per place: **owned-init** (live), **moved-out** (uninitialized), **borrowed-ref(n)**,
**borrowed-mut**. Copy values are exempt from all judgments below.

**J1 — move.** `move(x)` where `x` is owned-init transfers ownership; afterwards `x` is
moved-out until reassigned.
- `move(x)` where `x` is moved-out → `SE001 use-after-move`.
- `move(x)` while any borrow of `x` is live → `SE005 move-while-borrowed`.

**J2 — use.** Reading any place rooted at a moved-out variable → `SE001 use-after-move`.

**J3 — explicit transfer.** Ownership transfer is always spelled in source. Passing an
owned-init non-Copy value to an `Owned` parameter without `move()` → `SE002 missing-move`.
Plain rebinding `y = x` of a live non-Copy `x` → `SE003 implicit-transfer` (write
`y = move(x)`). A moved-out or never-initialized name may be freely (re)assigned.

**J4 — borrows.** At any program point, a place admits **any number of `Ref` XOR exactly one
`Mut`**. Borrows are function-call-scoped in Tier 0: created at a call, dead when it returns;
plus loop-scoped `for` borrows (§5.4). Violation → `SE004 conflicting-borrow`.
Since Tier-0 call arguments are evaluated for one call at a time, `SE004` arises via `for`-loop
borrows (§5.4) and self-aliasing calls (`xs.extend(xs)` — `Mut` receiver + `Ref` arg on the
same place).

**J5 — no stored/returned borrows.** `Ref`/`Mut` never appear in return position
(`SE209 returned-borrow`, Tier-0 decision — see decisions.md D2), never in container element
types, never on locals bound from a borrow (a call argument is the only borrow site).
Return values are always owned by the caller.

**J6 — drop.** A non-Copy value still owned-init at the end of its binding's lexical scope is
dropped there, in reverse declaration order. Drops are unobservable in Tier 0 (no destructors),
so scope-end vs ASAP timing is a backend freedom; the native backend documents scope-end (§10).

**J7 — aliasing.** `b = a` for non-Copy `a` without `move` is `SE003`; there is no way to
create two owners. `b = move(a); a.append(1)` is `SE001` on `a`.

**J8 — conditional moves.** A place moved on *some* control-flow path into a join point is
**maybe-moved** at the join: any use → `SE001`, any re-move → `SE001`. Reassignment on all
paths restores owned-init. A `move` in a loop body of a value bound outside the loop is
`SE001` at the loop head on iteration 2 (fixed-point rule; Phase-2 implementation).

---

## 5. Places & Element Access

A **place** is a path: variable, `x[i]` (list index / dict key), and (Tier 1) `x.f`.

### 5.1 Reading elements

- Copy element type: `y = xs[i]` copies. Unrestricted.
- Non-Copy element type: `move(xs[i])` / `y = xs[i]` are `SE006 move-out-of-container` /
  `SE003` — a move-out would leave a hole. Sanctioned alternatives:
  1. `xs.pop()` / `xs.pop(i)` / `d.pop(k)` — remove **and** transfer ownership;
  2. borrow in place: `f(xs[i])` into a `Ref`/`Mut` parameter, or `xs[i].method()` — the
     element is borrowed for the duration of that call;
  3. `xs[i] = new_value` — overwrite; the old element is dropped.

### 5.2 Writing elements

`xs[i] = v` and `d[k] = v` take `Mut` on the container; a non-Copy `v` requires
`xs[i] = move(v)` (J3).

### 5.3 Nested places

Rules apply to the outermost non-Copy segment: `grid[i][j] = 5` needs `Mut` on `grid`;
`move(grid[i])` is `SE006`.

### 5.4 `for` loops

`for x in xs:` takes a **`Ref` borrow of `xs` for the entire loop body**. Consequences:
- Any `Mut` use of `xs` inside the body (`xs.append`, `xs[i] = ...`, `xs.pop()`) is
  `SE004 conflicting-borrow` — this is the iterator-invalidation rule.
- `move(xs)` inside the body is `SE005`.
- Loop variable semantics: Copy element type → `x` is a per-iteration copy, freely usable.
  Non-Copy → `x` is a `Ref[T]` valid for one iteration: it may be read and have `Ref`-methods
  called, but `move(x)` is `SE007 move-loop-variable` and storing it is `SE209`/J5.
- In-place element mutation in Tier 0 is written `for i in range(len(xs)): xs[i] = ...`.
- `for x in range(...)` / `d.keys()` / `d.values()` / `d.items()` / `enumerate(xs)` borrow the
  underlying container identically (`range` borrows nothing).

---

## 6. `Optional[T]` narrowing

`T | None` is Tier 0. It compiles to Rust `Option<T>` (Phase 1).

- A value of type `T | None` supports **only**: `is None` / `is not None` tests, `==`/`!=`
  against a `T`-comparable when `T` is Copy (CPython semantics), passing/returning as
  `T | None`, and reassignment. Any `T`-operation on an unnarrowed optional is
  `SE210 unnarrowed-optional`.
- **Narrowing judgment:** after `if x is not None:` the name `x` has type `T` inside the
  then-branch; after `if x is None:` it has type `T` in the else-branch. `if x is None: return`
  (or `break`/`continue`) narrows `x` to `T` for the remainder of the scope. Narrowing applies
  to **names only**, not indexed places (`xs[i] is not None` narrows nothing — bind it first:
  `v = d.get(k)`).
- Narrowing is invalidated by any reassignment of `x` and, for non-Copy `x`, by any `Mut`
  borrow of `x`.
- No other unions exist in Tier 0 (`A | B` → `SE201`).

---

## 7. Call-Site Conventions

The parameter annotation decides what the caller gives up:

| Parameter | Call site | Meaning |
|---|---|---|
| `Ref[T]` | `f(xs)` | immutable borrow for the duration of the call |
| `Mut[T]` | `f(xs)` | exclusive borrow for the duration of the call |
| `Owned[T]` | `f(move(xs))` | ownership transfer; `move()` **required** (J3) |
| bare `T`, Copy | `f(x)` | copy |
| bare `T`, non-Copy | — | `SE203`: non-Copy parameters must state a convention |

- Copy types never take a marker and never use `Ref`/`Mut`/`Owned` wrappers
  (`SE202` on `Ref[int]`).
- A fresh temporary (literal, call result) passed to an `Owned` parameter needs no `move()`:
  `f([1, 2])` and `g(make_list())` are legal — only *named* live values require the marker.
- Return values are always owned by the caller (J5).

### 7.1 Builtin receiver/argument conventions

| Operation | Receiver | Arguments |
|---|---|---|
| `len(xs)`, `sum(xs)`, `min(xs)`, `max(xs)`, `x in xs` | `Ref` | — |
| `print(...)`, `str(x)`, f-string interpolation | `Ref` each | — |
| `xs.append(v)`, `xs.insert(i, v)` | `Mut` | `v` `Owned` → `move(v)` if non-Copy named |
| `xs[i] = v`, `d[k] = v` | `Mut` | `v` `Owned` (§5.2) |
| `xs.pop()`, `xs.pop(i)`, `d.pop(k)` | `Mut` | returns an **owned** element |
| `xs.extend(ys)` | `Mut` | `ys` `Ref` (elements copied; non-Copy element type → `SE211 extend-non-copy`, use a loop with `move`) |
| `xs.clear()`, `xs.reverse()`, `xs.sort()` | `Mut` | — |
| `d.get(k)` | `Ref` | returns `V \| None` (Copy `V` copies; non-Copy `V` → `SE212 get-non-copy`, use `k in d` + `d[k]` borrow or `d.pop(k)`) |
| `d.keys()`, `d.values()`, `d.items()` | `Ref` (for-loop position only) | — |
| `s.split(sep)`, `s.strip()`, ... (all `str` methods) | `Ref` (str is Copy anyway) | new owned `str`/`list[str]` |

---

## 8. Tier-0 Builtins Surface

Anything not listed is `SE201`.

- **Functions:** `print`, `len`, `range`, `enumerate`, `sum`, `min`, `max`, `abs`, `str`,
  `int`, `float`, `bool`, `input`, `move` (from the shim).
- **Syntax:** f-strings; format specs limited to `{x}`, `{x!r}`, `{x:.Nf}`, `{x:d}`,
  width/fill forms `{x:>N}`/`{x:<N}`/`{x:^N}` — output must match CPython byte-for-byte.
- **`str` methods:** `split` (no-arg and sep forms), `join`, `strip`, `lstrip`, `rstrip`,
  `startswith`, `endswith`, `find`, `replace`, `upper`, `lower`.
- **`list` methods:** `append`, `pop`, `insert`, `extend`, `clear`, `reverse`,
  `sort` (key-less only).
- **`dict` methods:** `get` (1-arg), `keys`, `values`, `items`, `pop` (1-arg), `in` operator.
- **I/O:** `print` and `input` only. `open()` is Tier 1; `sys.argv`/`sys.exit` are Tier 1.

`min`/`max`/`sum` operate on `list[int]` / `list[float]` (and 2-arg scalar `min`/`max`);
`sorted`, `map`, `filter`, `zip`, `any`, `all` are **not** Tier 0.

---

## 9. Modules, Imports, Entry Point

**Three bins.** `serp check` follows every import and sorts it:
1. **Serpentine modules** — project `.py` files in the subset: checked and compiled together
   (whole-program compilation).
2. **The shim** — `from serpentine import ...`: recognized, type-checked as the ownership
   vocabulary, erased at compile time.
3. **Everything else** — stdlib, site-packages: `SE213 foreign-import` at the import site.

**Module-level code.** Allowed: bin-1/bin-2 imports, `def`s, `Copy`-typed constants with
literal/constant-foldable initializers, and the entry guard. Everything else →
`SE205`. Mutable (non-Copy or reassigned) globals → `SE206`.

**Entry point.** `serp build` recognizes

```python
if __name__ == "__main__":
    main()
```

and makes `main()` (a zero-parameter, `-> None` function) the native entry point; override
with `serp build --entry`. A program with neither is check-only (library). CPython behavior is
untouched by construction.

---

## 10. Documented Divergences (native vs CPython)

The **complete** list. Anything else that differs is a Serpentine bug.

| # | Behavior | CPython | Serpentine native | Verdict |
|---|---|---|---|---|
| D1 | `int` width | arbitrary precision | 64-bit signed; overflow **traps** with `OverflowError` (never wraps) | loudest divergence; `bigint` opt-in later |
| D2 | destruction timing | refcount + GC, unordered `__del__` | deterministic at scope end (J6) | unobservable in Tier 0 (no destructors) |
| D3 | `id()` / `is` | object identity | no stable identity | rejected by checker (`SE207`) except `is None` |
| D4 | `//`, `%` on negatives | floor semantics (`-7 // 2 == -4`) | **must match** — codegen emits floor-div/mod helpers (Rust/LLVM truncate) | fixed in codegen, not documented away |
| D5 | `bool` in arithmetic | `True + 1 == 2` | rejected (`SE208`); write `int(b)` | checker |
| D6 | container `repr`, f-string output | CPython repr rules | **must match** byte-for-byte | fixed in runtime |
| D7 | `float` repr | shortest-roundtrip algorithm | **must match** — Ryū/grisu in runtime | fixed in runtime |
| D8 | dict ordering | insertion-ordered | **must match** — insertion-ordered impl | fixed in runtime |
| D9 | unhandled runtime error | traceback + exit 1 | same error class + message + exit 1; **traceback frames best-effort** | documented (§11) |
| D10 | recursion depth | `RecursionError` ≈ 1000 frames | native stack, no artificial limit | documented |
| D11 | division by zero float ops | `ZeroDivisionError` | must match (no IEEE inf leak) | fixed in codegen |
| D12 | stdout line endings | OS text mode (`\r\n` on Windows) | always `\n` | documented; differential harness normalizes |

Rule: divergences must be either checker-rejected (D3, D5), fixed-in-implementation (D4, D6,
D7, D8, D11), or loud documented decisions (D1, D2, D9, D10). **Never silent drift.**

---

## 11. Fatal Runtime-Error Model (Tier 0)

Tier 0 has runtime errors but no `try`. They are **fatal in both execution modes** — the moral
equivalent of `panic=abort` — preserving the Dual-Execution Guarantee.

### 11.1 Error classes and messages

Native binaries always bounds-check; there is no unsafe fast mode in v1. On error, the native
binary prints to **stderr** exactly:

```
<ErrorClass>: <message>
```

with the CPython 3.12 message text, and exits with **status 1** (CPython's unhandled-exception
status). Traceback frames are best-effort and not part of the guarantee (D9).

| Trigger | Class: message |
|---|---|
| `xs[i]`, i out of range | `IndexError: list index out of range` |
| `xs.pop()` on empty | `IndexError: pop from empty list` |
| `xs.pop(i)`, i out of range | `IndexError: pop index out of range` |
| `d[k]`, missing key | `KeyError: <repr of k>` |
| `d.pop(k)`, missing key | `KeyError: <repr of k>` |
| int `//`, `%`, `/` by zero | `ZeroDivisionError: integer division or modulo by zero` / `ZeroDivisionError: division by zero` |
| float `/` by zero | `ZeroDivisionError: float division by zero` |
| `int(s)` unparsable | `ValueError: invalid literal for int() with base 10: <repr of s>` |
| `float(s)` unparsable | `ValueError: could not convert string to float: <repr of s>` |
| int overflow (native only) | `OverflowError: Serpentine int operation overflowed 64 bits` (D1 — no CPython counterpart) |
| `min([])` / `max([])` | `ValueError: min() iterable argument is empty` / `max()` … |

### 11.2 Implementation requirement

Runtime errors are represented as **error values** in the runtime from day one — the abort is
the last step at the top level, not an `abort()` at the error site. When Tier-1 exceptions
land, these become ordinary catchable exceptions without a runtime rewrite.

---

## 12. Diagnostics — error codes

Every checker rejection carries a stable code. `tests/reject/` files reference these codes;
they are frozen once released.

### Ownership (SE0xx)

| Code | Name | Judgment |
|---|---|---|
| SE001 | use-after-move | J1, J2, J8 |
| SE002 | missing-move | J3 |
| SE003 | implicit-transfer | J3, J7 |
| SE004 | conflicting-borrow | J4, §5.4 |
| SE005 | move-while-borrowed | J1, §5.4 |
| SE006 | move-out-of-container | §5.1 |
| SE007 | move-loop-variable | §5.4 |
| SE008 | move-out-of-borrow | Phase 2: moving a field (or the whole) out of a `Ref`/`Mut` parameter would leave the caller's value with a hole (rustc E0507 parity) |

### Types & subset (SE2xx)

| Code | Name |
|---|---|
| SE201 | unsupported-feature |
| SE202 | invalid-wrapper-position |
| SE203 | missing-annotation |
| SE204 | unknown-element-type |
| SE205 | module-level-statement |
| SE206 | mutable-global |
| SE207 | identity-comparison |
| SE208 | bool-arithmetic |
| SE209 | returned-borrow |
| SE210 | unnarrowed-optional |
| SE211 | extend-non-copy |
| SE212 | get-non-copy |
| SE213 | foreign-import |
| SE214 | type-mismatch |
| SE215 | unsatisfied-protocol (Tier 2) |

Diagnostic format: `error[SE001]: use of moved value 'xs'` with a primary source span;
Phase 2 added secondary "value moved here" labels and `help:` suggestion lines.

---

## 13. Tier-1 surface (Phase 2) — summary

Normative details live in the implementation + test corpus until the Tier-1 spec pass;
this section records the shipped surface and its rules of thumb.

- **Classes** — `@dataclass` (imported from `serpentine`) with annotated fields and
  methods; no inheritance (only a `Generic[...]` base), no field defaults, no dunder
  methods. Instances are non-Copy owned values; dataclass `==`/`repr` follow CPython.
  `self` must be annotated `Ref[C]` or `Mut[C]` (`Owned` self is Tier 2). Classes that
  contain themselves by value are rejected (SE214); use `Shared`/`Weak`/`list`.
- **Field places** — the checker is field-sensitive one level deep: `move(x.f)` leaves
  `x.g` usable; using the whole `x` is SE001 until `x.f` is re-assigned; assigning a
  field of a wholly-moved value is SE001; moving out of a borrowed parameter is SE008.
- **Generics** — module-level `T = TypeVar("T")`; generic functions and generic classes
  (`class Box(Generic[T])`). Monomorphized per call-site/constructor argument types;
  type arguments must be inferable from arguments (else SE214/SE204).
- **`Shared[T]` / `Weak[T]`** — `share(move(x))`, `downgrade(s)`, `upgrade(w) ->
  Shared[T] | None`. Handles copy freely; reads/writes go through a runtime borrow
  (conflict → catchable RuntimeError). Cycles leak (decisions.md D3).
- **Exceptions** — `try/except/finally` (no `else`), `raise Class("msg")`, bare `raise`
  in handlers, built-in exception classes only. `try` is a sub-scope with the E1
  maybe-moved join (decisions.md D1). Restrictions: no `return` inside a try with
  `finally`; no `break`/`continue` out of a try; no `return`/`break`/`continue` inside
  `finally`. Tier-0 runtime errors are catchable.
- **Builtins** — `open(path, mode)` with modes r/w/a, `.read()`, `.write(s)`,
  `.close()`; dropping a file closes it. `import sys`: `sys.argv` (owned copy),
  `sys.exit(int)`.
- **`from __future__ import annotations`** — permitted and recommended in files that
  mention class names in annotations (CPython forward-reference parity).

---

## 14. Tier-2 surface (Phase 4) — summary

Shipped in demand order from the Phase-2 corpus study (`archive/corpus-study.md`).
Normative details live in the implementation + test corpus (tests/accept/050–055,
tests/reject/r029, r036, r051, r052).

- **str indexing & slicing** — `s[i]` (negative indices; out of range raises
  `IndexError: string index out of range`) and `s[a:b]` (clamping, negatives, no step;
  a step slice is SE201). Slicing is str-only in Tier 2.
- **Comprehensions** — `[expr for x in it if cond]` and `{k: v for x in it if cond}`;
  exactly one `for` clause, at most one `if` clause; targets are one or two names.
  The iterable is Ref-borrowed for the whole expression (mutating or moving anything
  it reaches inside the body is SE004/SE005); the element expression must produce a
  Copy or freshly-constructed value (SE003 otherwise). `is None` narrowing applies
  inside the `if` clause.
- **`sorted()`** — `sorted(xs)` for `list[int|float|str]`; `sorted(xs, key=lambda v:
  expr)` for lists of Copy elements, key returning int/float/str. Stable, returns a new
  list. The key lambda is the only closure form in Tier 2: one parameter, expression
  body, reads of enclosing locals allowed, mutation/moves of anything reachable
  rejected (SE004/SE005). `reverse=` is not supported (SE201).
- **`with open(...) as f:`** — RAII sugar for files; exactly one context manager, only
  `open()`. The target must be a fresh name, is scoped to the block (unknown after —
  keeps "closed at block end" true in both execution modes), and cannot be moved out
  (SE005). Errors inside the block still close the file on both sides.
- **Default parameter values** — functions and methods; literal int/float/bool/str/None
  constants only (SE201 otherwise), not on `Ref`/`Mut` parameters (SE202), not on
  generic parameters. Call sites may omit trailing defaulted arguments; keyword calls
  remain unsupported.
- **Iterators** — `zip(a, b)` (two lists), `reversed(xs)`, and `for ch in s:` (str
  iteration, one character per step) join `range`/`enumerate`/dict views. All are
  for/comprehension iterator forms; user-defined `__iter__`/`__next__` objects are
  deferred (decisions.md D7 — they are stored borrows).
- **Protocols** — `class P(Protocol):` (import `Protocol` from `serpentine`) declares
  method signatures with `...` bodies; `T = TypeVar("T", bound=P)` constrains a generic
  function/class/method. Satisfaction is structural and checked at every inference site
  (SE215): required methods must exist with identical conventions, parameter types, and
  return type. Protocols are bounds only — not usable as value types.
- **New builtins** — `round(x)` (ties-even → int), `round(x, n)` (→ float), `ord(c)`,
  `chr(i)`. Divergences: `chr()` of a lone surrogate raises `ValueError` natively;
  `round(x, n)` with `n < 0` rounds the binary value (CPython rounds decimal digits).
- **Tooling (not language)** — `serpentine_lang.api.check_file/check_source` is the
  checker-as-library surface; `serp lsp` serves LSP diagnostics over stdio with unsaved
  buffer overlays. The CPython interop boundary refuses foreign imports (SE213,
  decisions.md D6, `guides/interop.md`).

### 14.1 Phase-4 backlog additions

- **Owned (consuming) `self`** — `def into_x(self: Owned[C]) -> T`. The call site must
  transfer the receiver explicitly: `move(x).into_x()` (SE002 otherwise); a
  freshly-constructed receiver (`C(...).into_x()`) needs no move. The receiver is
  moved-from after the call (SE001 on later use). Shared receivers cannot be consumed
  (SE006). Protocol methods still take Ref/Mut self only.
- **Field-place narrowing** — `if x.f is not None:` narrows the one-level field place
  `x.f` (plain dataclass locals/params only, never through `Shared`). The narrow dies on
  any assignment to `x` or `x.f`, and on any `Mut` use of `x` (calls, methods, item
  writes). Works in `if`/`while` tests and comprehension conditions.
- **Named element borrows** — `first = rows[i]` (list or dict subscript on a name, one
  level, non-Copy non-Optional element) binds `first` as a **scoped Ref borrow**: it
  lives to the end of the enclosing block, during which the container cannot be mutated
  or moved (SE004/SE005) and `first` cannot be moved (SE008), mutated through (SE004),
  re-assigned (SE201), or returned (SE209). The name is unknown after the block. Copy
  elements keep their existing copy semantics. Shared containers stay SE006.
- **First-class iterators** — `it = iter(xs)` (list of Copy elements, named variable,
  fresh target) binds a block-scoped iterator that Ref-borrows `xs`; `next(it)` yields
  the next element and raises catchable `StopIteration` when exhausted (added to the
  known exception classes). The iterator cannot be printed, passed, moved, or iterated
  by `for`; drain it with `try: while True: ... except StopIteration:`. Non-Copy element
  lists are rejected (SE201) — `next()` copies elements out.
- **String runtime** — small-string optimization (≤22 bytes inline, zero allocation;
  longer strings `Rc<str>`); ASCII fast paths for `len`/index/slice/`find`. String
  copies remain O(1); `bench_strings` reaches CPython parity (guides/benchmarks.md).
