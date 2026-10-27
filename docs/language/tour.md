# The Serpentine Language Tour

Serpentine is a compiled subset of Python with Rust-style ownership instead of a garbage
collector. One `.py` file, two ways to run it — always with identical output:

```
python tool.py          # CPython: full ecosystem, debugger, REPL
serp build tool.py      # native binary: ~140 KB, no Python, no GC; numeric code up to ~140x faster, strings ≈ CPython
```

This is the **Dual-Execution Guarantee**. It works because `serp check` only accepts
programs whose behavior is identical under both executions (the complete list of
deliberate differences is in [divergences.md](divergences.md)).

## Hello, ownership

```python
from serpentine import move


def main() -> None:
    xs: list[int] = [1, 2, 3]
    ys = move(xs)          # ownership transfers; xs is gone
    print(len(ys))


if __name__ == "__main__":
    main()
```

Everything is annotated, and non-Copy values (lists, dicts, class instances) have exactly
one owner. `move()` is a no-op at runtime (the shim makes it the identity function) — it
exists so transfers are visible in the source. Forgetting it is error `SE002/SE003`; using
`xs` after the move is `SE001`. See the [ownership guide](ownership.md).

## The type surface

- **Copy types** (freely duplicated): `int` (64-bit, overflow traps), `float`, `bool`,
  `str` (O(1) copies), `None`, tuples of Copy types.
- **Owned types** (single owner, moved explicitly): `list[T]`, `dict[K, V]`, dataclasses.
- **`T | None`** with `is None` narrowing.
- **`Shared[T]` / `Weak[T]`**: refcounted escape hatch (`share`, `downgrade`, `upgrade`).

## Functions and calls

Parameters declare a **convention**: plain type for Copy values, `Ref[T]` (shared borrow),
`Mut[T]` (exclusive borrow), or `Owned[T]` (transfer, caller writes `move(...)`).

```python
from serpentine import Ref, Mut, Owned, move


def total(xs: Ref[list[int]]) -> int:
    return sum(xs)


def push_twice(xs: Mut[list[int]], v: int) -> None:
    xs.append(v)
    xs.append(v)


def consume(xs: Owned[list[int]]) -> int:
    return len(xs)


def main() -> None:
    nums: list[int] = [1, 2]
    push_twice(nums, 7)
    print(total(nums))
    print(consume(move(nums)))
```

Defaults are allowed for literal values: `def pad(s: str, width: int = 8) -> str`.

## Classes, generics, protocols

```python
from __future__ import annotations
from serpentine import Ref, Mut, Protocol, TypeVar, Generic, dataclass


class Named(Protocol):
    def label(self: Ref[Named]) -> str: ...


T = TypeVar("T", bound=Named)


@dataclass
class Point:
    x: int
    y: int

    def label(self: Ref[Point]) -> str:
        return f"({self.x}, {self.y})"


def show(v: Ref[T]) -> None:
    print(v.label())
```

Dataclasses only (no inheritance); `self` states its convention; generics monomorphize per
call site; protocol bounds are checked structurally (`SE215` when unsatisfied).

## Control flow & sugar

`if`/`while`/`for` over lists, `range`, `enumerate`, `zip`, `reversed`, dict views, and
strings; `try/except/finally` over the built-in exception classes (runtime errors like
`IndexError` are catchable); comprehensions; `sorted(xs, key=lambda v: ...)`;
string indexing and slicing `s[a:b]`; f-strings; `with open(path) as f:`.

```python
def word_lengths(text: str) -> dict[str, int]:
    return {w: len(w) for w in text.split() if len(w) > 2}
```

## The toolchain

| Command | What it does |
|---|---|
| `serp check tool.py` | type + borrow check, rustc-quality diagnostics |
| `serp build tool.py` | native binary via direct LLVM (release runs a rustc oracle pass; `--backend rust` for the Rust backend) |
| `serp llvm tool.py` | build via the LLVM backend and run (`--release`, `--emit-ir`) |
| `serp lsp` | LSP server for editor diagnostics |

A complete worked example — a JSON parser developed under CPython and deployed as a native
binary — lives at [`examples/json_parser.py`](../../examples/json_parser.py).

## What's deliberately missing

No inheritance, no closures beyond `sorted` keys, no generators/`yield` (but
`iter()`/`next()` over lists work), no `async`, no mutable globals, no foreign imports
in native builds ([interop.md](../guides/interop.md)). The subset grows by demand order from
real-code corpus studies — see `../spec.md` for the normative
surface.
