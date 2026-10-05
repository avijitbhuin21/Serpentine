# Migrating Python Code to Serpentine

What actually changes when you port an ordinary Python script, in the order you will hit
it. The corpus study (archived) found that numeric code, str/dict
processing, and dataclass-based code pass nearly unchanged; the friction is concentrated
below.

## 0. Structure requirements (one-time)

- Everything annotated: parameters, returns, and first bindings of empty literals.
- Module level may contain only imports, `def`s, classes, Copy-typed constants with
  literal initializers, and the `if __name__ == "__main__":` guard.
- The entry file needs that guard, calling a zero-argument function.
- Imports: your own modules in the same directory, `import sys`, and
  `from serpentine import ...`. Everything else is refused natively
  ([interop.md](interop.md)) — `pip install serpentine-shim` makes the `serpentine`
  imports work under CPython.

## 1. Add conventions to signatures

For each non-Copy parameter decide: read it (`Ref`), mutate it (`Mut`), or keep it
(`Owned` — callers must `move`). Copy parameters (`int`, `float`, `bool`, `str`) stay
plain. This is usually the bulk of the diff and it is mechanical — the checker's `help:`
lines tell you which one you meant.

## 2. Make transfers explicit

Wherever a list/dict/object changes hands — rebinding, `append`, storing in a field or
container, constructor arguments — write `move(x)`. If you *didn't* mean to give it away,
you meant a borrow: restructure to call a function taking `Ref`/`Mut` instead of aliasing
(`b = a` aliasing is exactly what the language removes).

## 3. Restructure the rejected idioms

| Python habit | Serpentine replacement |
|---|---|
| `first = rows[0]` (keep using rows) | works — a scoped borrow; the container is frozen until block end |
| `d.get(k)` for non-Copy values | `if k in d: ... d[k]` in place, or `d.pop(k)` |
| mutate a list while iterating it | collect changes, apply after the loop |
| classes with inheritance | composition, or protocols for the interface |
| `lambda`/closures | `sorted(xs, key=lambda v: ...)` is the supported form |
| generators / `yield` | build and return a list, or `it = iter(xs)` + `next(it)` |
| big ints | stay ≤ 64 bits or keep the tool on CPython |
| mutable globals | pass state explicitly (usually a dataclass) |

## 4. Classes

Use `@dataclass` from `serpentine` with annotated fields (no defaults), annotate `self`
(`Ref[C]` for readers, `Mut[C]` for mutators), and break by-value cycles with
`Shared`/`Weak`/lists. Add `from __future__ import annotations` when methods mention
their own class.

## 5. Iterate with the checker, not against it

`serp check` (or `serp lsp` in your editor) after each step. Every error carries a stable
code, the span, and a suggested fix; the [ownership guide](../language/ownership.md) explains the
model behind them. When the checker finally says OK, `python tool.py` and the
`serp build` binary are guaranteed to agree — so port first, then debug logic under
CPython with the whole ecosystem, and ship the binary last.

## A worked example

`examples/json_parser.py` is a full recursive-descent JSON parser + serializer written
this way — dataclasses with `Mut[Parser]` methods, explicit moves into containers,
`with open`, and zero `Shared`. Reading it after this page is the fastest way to
internalize the dialect.
