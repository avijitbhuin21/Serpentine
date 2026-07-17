# serpentine-shim

The runtime companion of the [Serpentine](https://github.com/serpentine-lang/serpentine)
compiler. It provides the ownership vocabulary — `Owned`, `Ref`, `Mut`, `Shared`, `Weak`,
`move`, `@native` — as **runtime no-ops**, so a Serpentine program is also a valid, runnable
CPython program:

```python
from serpentine import Owned, Ref, move

def total(prices: Ref[list[float]]) -> float:
    return sum(prices)

def main() -> None:
    prices: Owned[list[float]] = [9.99, 4.50]
    print(total(prices))
    archive = move(prices)   # lambda x: x at runtime; a semantic move to `serp check`
```

Under CPython this package does nothing except make the imports resolve: the wrappers are
`typing.Annotated` aliases (so `Owned[list[float]]` *is* `list[float]` to any type checker)
and `move` returns its argument. All semantics live in the static checker, `serp check`.

This package is intentionally frozen and tiny: its public API is part of the Serpentine
language spec (SPEC.md).
