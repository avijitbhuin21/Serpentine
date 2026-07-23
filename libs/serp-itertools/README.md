# serp-itertools

Drop-in facade for CPython's `itertools`, written in the Serpentine subset.
Iterators are real lazy objects (classes implementing `__iter__`/`__next__`),
so `count()` and `cycle()` are genuinely infinite, `next(it)` works, and
`for x in it:` drains them exactly like CPython. Swap
`import serp_itertools` for `import itertools` on the supported surface.

Verified against the real `itertools` with a randomized differential
(8801/8801 checks) and byte-identical across CPython + both native backends.

## Supported API

`count(start=0, step=1)`, `cycle(xs)`, `repeat(obj[, times])`,
`chain(a, b)`, `islice(xs, stop | start, stop[, step])`,
`compress(data, selectors)`, `accumulate(xs)`, `pairwise(xs)`,
`product(a, b)`, `zip_longest(a, b, fillvalue)`,
`takewhile(pred, xs)`, `dropwhile(pred, xs)`, `filterfalse(pred, xs)`,
`batched(xs, n)`, `permutations(xs[, r])`, `combinations(xs, r)`,
`combinations_with_replacement(xs, r)`.

## Divergences from CPython

- Inputs are `list[T]` (the subset's iterable) with Copy element types;
  iterators snapshot their input at construction time.
- `chain`/`product`/`zip_longest` take exactly two inputs of the same
  element type (no variadic forms).
- `permutations`/`combinations`/`combinations_with_replacement`/`batched`
  yield `list[T]` rows instead of tuples (row arity is not statically known).
- `repeat(x, times)` uses `times=-1` as the "not given" sentinel (infinite);
  CPython treats negative counts as empty.
- `islice` uses `stop=-2` as the "one-argument form" sentinel and `stop=-1`
  for CPython's `None` (unbounded).
- `accumulate` supports plain `+` accumulation only (no `func`/`initial`).
- `zip_longest` requires `fillvalue`; `count` is int-only.
- `starmap`, `groupby` and `tee` are not provided (`*args` application,
  nested group iterators, and tuple-of-iterators returns are out of subset).

## Install

```
serp add serp-itertools
pip install serp-itertools
```
