# The Ownership Guide

Serpentine removes the garbage collector by making ownership part of the language.
This guide is the mental model; `SPEC.md` §4–§7 is the normative rulebook.

## 1. Two kinds of values

**Copy values** — `int`, `float`, `bool`, `str`, `None`, tuples of these. Assignments and
calls duplicate them; there is nothing to track. (`str` is refcounted internally so the
copy is O(1); it still *behaves* like a value.)

**Owned values** — `list[T]`, `dict[K, V]`, dataclass instances, open files. Each has
exactly one owner at any time. When the owner's scope ends, the value is freed —
deterministically, with no collector pause.

## 2. Moves are explicit

Rebinding an owned value would silently create a second owner, so it requires `move`:

```python
b = a               # SE003: implicit transfer
b = move(a)         # ok: b owns it now; a is uninitialized
print(a)            # SE001: use of moved value 'a'
```

The same applies to storing into containers/fields and passing to `Owned` parameters:

```python
xs.append(move(row))
grid.rows = move(rows)
consume(move(xs))
```

`move()` comes from the shim and is the identity function at runtime — the semantics live
entirely in `serp check`. Re-assigning a moved variable makes it usable again; the checker
runs a fixed-point dataflow, so a `move` inside a loop that isn't re-initialized on every
path is caught (`SE001` "moved on some paths").

## 3. Borrows are call-scoped

`Ref[T]` (any number, read-only) and `Mut[T]` (exactly one, exclusive) exist **only on
parameters**. A borrow lasts for the duration of the call — there are no named lifetimes,
no borrows stored in fields or locals, and no returned borrows (`SE209`). This is the big
simplification vs Rust: you never reason about lifetime annotations, only about a single
call frame.

The XOR rule shows up at call sites: `merge(xs, xs)` where one side is `Mut` is `SE004`;
`xs.extend(xs)` likewise.

## 4. Loops and iteration

`for x in xs:` Ref-borrows `xs` for the whole loop body. Inside the body you can read
`xs` freely, but mutating it (`xs.append`, `xs[i] = v`) is `SE004` — iterator
invalidation, caught statically. The loop variable of a non-Copy element list is a
per-iteration borrow: it cannot be moved (`SE007`) or mutated through (`SE004`).

Comprehensions and `sorted(key=...)` lambdas follow the same rule: the iterated container
is borrowed for the whole expression, and the produced elements must be Copy or freshly
constructed (`SE003`) — you cannot duplicate owned elements by comprehension.

## 5. Containers hold their elements

Reading a non-Copy element out of a container is not a move (that would leave a hole):

```python
first = rows[0]          # SE006: cannot copy a non-Copy element out
```

Your options: index in place (`rows[0].append(1)`), pop it (`rows.pop(0)` transfers
ownership out), or overwrite it. Dict `get()` on non-Copy values is `SE212` — use
`k in d` plus `d[k]` in place, or `d.pop(k)`.

## 6. Fields: one level of precision

`move(x.f)` moves just that field: `x.g` stays usable, the whole `x` is unusable until
`x.f` is re-assigned. Moving out of a *borrowed* parameter is `SE008` — the caller still
owns the whole value and must not receive it back with a hole.

## 7. When ownership is the wrong tool: `Shared`

Graphs, caches, and true sharing use the escape hatch:

```python
s = share(move(node))     # Shared[Node]: refcounted handle, copies freely
w = downgrade(s)          # Weak[Node]: does not keep it alive
back = upgrade(w)         # Shared[Node] | None
```

Reads/writes go through a runtime borrow check (a conflict raises a catchable
`RuntimeError`), and cycles leak unless broken with `Weak` (DECISIONS.md D3). Prefer
ownership; reach for `Shared` when the shape of the data demands it.

## 8. Files and `with`

An open file is an owned value; dropping it closes it. `with open(path) as f:` makes the
close point explicit: `f` scopes to the block, cannot be moved out (`SE005`), and the name
is unknown afterwards — so "use after close" is impossible to write.

## 9. Reading the errors

Every rejection has a stable code (`SPEC.md` §12), a primary span, a "moved here"
secondary label where relevant, and a `help:` line with the local fix. The intended
workflow is rustc's: read the first error, apply the suggested fix, re-check. The checker
agrees with rustc on the transpiled corpus by construction (`tools/run_rustc_agreement.py`),
so what it teaches you is real ownership, not a house dialect.
