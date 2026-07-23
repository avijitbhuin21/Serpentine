# Paper Prototype — Exceptions × Ownership (Tier 1)

> Phase-0 design exercise per ../archive/research.md §8.1. Nothing here is implemented; the goal is to
> prove the model is coherent *before* Tier 1, because exceptions interact with ownership more
> than any other feature. Adopted conclusions are recorded in ../decisions.md D1.

## 1. The problem

An exception is a non-local exit. Two ownership questions follow:

1. **Unwind drops:** values owned by frames/scopes being unwound must be dropped exactly once.
2. **Borrow boundaries:** a borrow created inside a `try` body may be live when control
   teleports to `except` — what is its extent?

## 2. Model: `try` is a sub-scope

The `try` body is a lexical sub-scope with two exits (fall-through, exceptional):

- **Borrows:** every borrow created inside the `try` body dies at both exits — i.e. at normal
  `try`-end AND at `except`/`finally` entry. Tier-0/1 borrows are call-scoped anyway
  (../spec.md J4/J5), so the only multi-statement borrows are `for`-loop borrows; a `for`
  containing a `try`, or a `try` containing a `for`, nests sub-scopes naturally.
- **Owned values:** a value whose binding is inside the `try` body and is still owned-init at
  the raise point is dropped during unwinding (Rust panic semantics). A value bound *before*
  the `try` is untouched by the unwind and stays live in `except`.

## 3. The hard case: maybe-moved at `except` entry

```python
def f(xs: Owned[list[int]]) -> None:
    try:
        g(move(xs))        # ownership left this frame...
        risky()            # ...then something raised
    except ValueError:
        print(len(xs))     # is xs live here?
```

At `except` entry, `xs` state depends on *where* the raise happened — before or after the
`move`. A path-sensitive answer is unimplementable; the sound merge is:

> **Rule E1:** at `except` entry, every place is in the **join** of its states at every
> potentially-raising point in the `try` body (plus `try` entry). A place moved anywhere in
> the body is *maybe-moved* in `except` → any use is `SE001`.

So the example is rejected. The fix is idiomatic and mechanical — move before the `try` or
don't reuse `xs` in the handler:

```python
    try:
        risky()
        g(move(xs))            # move as the last raising action
    except ValueError:
        return                 # xs not touched: fine — dropped by normal scope-end
```

**Corollary (E1a):** the unwind path must drop `xs` *only if it was not yet moved* — the
runtime needs a drop flag per maybe-moved place (rustc does exactly this with drop flags for
conditionally-moved locals). This is a codegen cost only on places that are moved inside a
`try`, which the checker can enumerate statically.

## 4. `finally`

`finally` runs on both exits, so it sees the same join as `except` (Rule E1). Additionally a
`finally` body may not `return`/`break`/`continue` (it would swallow the in-flight exception —
CPython 3.12 already warns; we reject, `SE201`-family). `raise` inside `finally` replaces the
in-flight exception, as in CPython.

## 5. What may be raised / caught (Tier-1 surface)

- Raisable: the built-in error classes of ../spec.md §11.1 plus `ValueError`/`RuntimeError`
  with a `str` message. User exception classes wait for Tier-1 classes.
- `except E:` and `except E as e:` — `e` is an **owned** value dropped at handler end;
  `raise` (bare re-raise) allowed inside a handler.
- Tier-0 fatal runtime errors (IndexError, KeyError, ZeroDivisionError, OverflowError, ...)
  become ordinary catchable exceptions — this is why ../spec.md §11.2 mandates error values, not
  aborts, in the runtime.

## 6. Backend sketch (evidence of feasibility)

Phase-1 Rust backend: raising functions return `Result<T, SerpErr>`; `try` lowers to a match
on the `?`-chain; drop flags for maybe-moved places lower to `Option<T>` locals (`None` =
moved). No unwinding machinery needed — which also keeps Backend B (LLVM) simple: it's just
control flow. Cost when no exception is thrown: one branch per raising call — acceptable, and
identical to what rustc generates for `?`.

## 7. Verdict

The sub-scope model + join rule E1 is sound, implementable with per-place drop flags, and
needs **no changes to Tier-0 rules** — J1–J8 already define the join semantics (J8
maybe-moved). Tier-1 exceptions are additive. Prototype passes.
