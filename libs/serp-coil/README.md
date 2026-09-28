# serp-coil — **Coil**, a numpy drop-in for Serpentine

```python
from serp_coil import array, arange, zeros, linspace, sqrt, mean, where, float64

a = array([1, 2, 3])                 # int64
b = linspace(0.0, 1.0, 3)            # float64
print(a * 2.5 + b)                   # [2.5  5.5  8.5]
print(f"{a > 1!r}")                  # array([False,  True,  True])
m = arange(6).reshape((2, 3))
print(m.T @ m, m[1, 2], mean(m))
c = zeros(5)
c[c == 0] = 7                         # boolean-mask assignment
print(sqrt(array([4, 9])), where(a > 1, a, 0), a.astype(float64))
```

The same file runs under CPython (`pip install serp-coil`) and compiles natively
(`serp add coil`). Everything is written in the Serpentine subset: no runtime
primitives, no C — the compiled loops are plain native code.

## What you get

| Area | Names |
| --- | --- |
| Construction | `array`, `asarray`, `zeros`, `ones`, `full`, `empty`, `*_like`, `arange`, `linspace`, `eye`, `identity`, `copy` |
| `ndarray` | `shape`, `ndim`, `size`, `dtype`, `T`, `len()`, `a[i]`, `a[i, j]`, `a[i] = v`, `a[i, j] = v`, `a[mask] = v`, `a[index_array] = v`, iteration (flat), `item`, `tolist`, `copy`, `astype`, `fill`, `reshape`, `flatten`, `ravel`, `transpose` |
| Operators | `+ - * / // % **` (array⊕array with broadcasting, array⊕scalar, scalar⊕array), `@`, unary `-`, `~`, comparisons `< <= > >= == !=` → bool arrays, `& \| ^` |
| Reductions | `sum`, `prod`, `mean`, `average`, `var`, `std` (`ddof=`), `min`, `max`, `amin`, `amax`, `ptp`, `argmin`, `argmax`, `all`, `any`, `cumsum`, `cumprod`, `median`, `percentile`, `quantile`, `count_nonzero`, `flatnonzero` — as methods and functions |
| Axis reductions (2-D) | `sum_axis`, `mean_axis`, `var_axis`, `std_axis`, `prod_axis`, `min_axis`, `max_axis`, `argmin_axis`, `argmax_axis`, `all_axis`, `any_axis`, `cumsum_axis` |
| Ufuncs | `abs`/`absolute`/`fabs`, `sqrt`, `cbrt`, `square`, `reciprocal`, `exp`, `exp2`, `expm1`, `log`, `log2`, `log10`, `log1p`, `sin`, `cos`, `tan`, `arcsin`, `arccos`, `arctan`, `arctan2`, `hypot`, `sinh`, `cosh`, `tanh`, `floor`, `ceil`, `trunc`, `fix`, `rint`, `round`/`around`/`round_`, `sign`, `negative`, `degrees`/`radians`/`rad2deg`/`deg2rad`, `isnan`, `isinf`, `isfinite`, `nan_to_num` |
| Binary functions | `add`, `subtract`, `multiply`, `divide`, `true_divide`, `floor_divide`, `mod`, `remainder`, `power`, `maximum`, `minimum`, `equal`, `not_equal`, `less`, `less_equal`, `greater`, `greater_equal`, `logical_and/or/xor/not`, `bitwise_and/or/xor`, `invert`, `clip`, `where`, `isclose`, `allclose`, `array_equal` |
| Selection & shape | `extract`/`compress` (`a[mask]`), `take` (`a[indices]`), `row` (`a[i]` on 2-D), `column` (`a[:, j]`), `slice_` (`a[start:stop:step]`), `repeat`, `tile`, `concatenate`, `vstack`, `hstack`, `append`, `diff`, `sort`, `argsort`, `unique`, `searchsorted`, `reshape`, `ravel`, `transpose`, `size`, `ndim`, `shape` |
| Linear algebra | `dot`, `vdot`, `inner`, `outer`, `matmul`, `trace`, `diag`, `norm`, `det`, `inv`, `solve` (numpy puts the last four under `np.linalg`) |
| Constants | `pi`, `e`, `euler_gamma`, `inf`, `nan`, dtype names `float64`, `int64`, `bool_` |

Printing is numpy-exact: `repr()`/`str()` reproduce numpy 2.x's `array2string`
(maxprec/unique float formatting, scientific switch-over, sign/`nan`/`inf`
padding, 75-column wrapping, `...` summarization above 1000 elements with the
`shape=` suffix, `dtype=` on empty arrays). `tests/test_printing.py` is diffed
byte-for-byte against numpy 2.4.6.

## Divergences from numpy (read this)

Coil is a drop-in for the *code you write*; the type system forces a few shapes to
differ. Every item below is deliberate.

- **Import style.** Serpentine has no `import x as y`, so it is
  `from serp_coil import array, sum, ...` rather than `np.array`. Module-level
  `sum`/`min`/`max`/`abs`/`round`/`all`/`any` shadow the builtins in *your*
  module only if you import them.
- **1-D and 2-D only.** Shapes are lists (`a.shape == [2, 3]`, prints `[2, 3]`,
  not `(2, 3)`); shape arguments accept `int`, `(r, c)` tuples or `[r, c]` lists.
- **Three dtypes**, stored as float64 with a tag: `float64`, `int64`, `bool`.
  `array([1, 2])` is `int64`, `array([1, 2.5])` is `float64`, `array([True])` is
  `bool`. Values above 2^53 lose integer precision. `dtype=` takes a string
  (`"float64"`, `"int64"`, `"bool"`, plus the usual aliases) or the exported
  names `float64`/`int64`/`bool_` — `dtype=float` (the Python type) is not
  expressible.
- **Scalars are floats.** `a[i]`, `a.sum()`, `a.max()`, `mean()` … return `float`
  even for int arrays (`print(array([1, 2]).sum())` → `3.0`, numpy prints `3`).
  `argmin`/`argmax`/`count_nonzero`/`searchsorted` return `int`; `all`/`any`
  return `bool`.
- **Integral scalars keep int arrays integral.** The compiler widens `2` and
  `2.0` to the same `float`, so `int_array * 2.0` stays `int64`
  (numpy: float64). Use `.astype(float64)` when you need the promotion.
- **`a[i]` on a 2-D array is an error** (elements are floats, rows are arrays):
  use `a[i, j]`, `row(a, i)`, `column(a, j)`. **No slicing syntax** on arrays:
  use `slice_(a, start, stop, step)`, `take(a, [...])`, `extract(mask, a)`.
  Boolean/fancy indexing *on the left* of an assignment works (`a[mask] = v`,
  `a[idx] = v`).
- **`axis=` keywords don't exist**: a function returns one static type, so the
  array-returning axis reductions are the separate `*_axis(a, axis)` functions.
- **Two-array stacking**: `concatenate(a, b, axis=0)`, `vstack(a, b)`,
  `hstack(a, b)` take two arrays, not a sequence.
- **`dot`/`matmul`/`@` always return an array** — a 1-D·1-D product is a
  1-element array (`.item()` for the float); `vdot`/`inner` return the float.
- **Iteration is flat** (`for x in a` yields floats, also on 2-D arrays).
- `average(a, weights)` takes the weights as an owned array; `argsort` is stable
  (numpy's default quicksort is not, so tie order can differ); `sort`/`unique`
  place `nan` last like numpy.
- Reductions use numpy's pairwise summation, so `sum`/`mean`/`std` match numpy to
  the last bit on the same data; `dot`/`det`/`inv`/`solve` are plain loops and
  can differ from BLAS/LAPACK in the last ulp.
- Not covered: `np.random`, 3-D+ arrays, complex/str/object dtypes, views
  (every operation copies), structured arrays, `einsum`, FFT, broadcasting of
  in-place `+=` (write `a = a + b`).

## Errors

Shape/broadcast/index errors raise `ValueError`/`IndexError`/`TypeError` with
numpy's wording (`operands could not be broadcast together with shapes (3,) (2,) `,
`index 3 is out of bounds for axis 0 with size 3`, `cannot reshape array of size 3
into shape (2,2)`, …). Float edge cases follow numpy, not Python: `x / 0` is
`inf`/`nan`, `sqrt(-1.0)` is `nan`, `log(0.0)` is `-inf`, negative integer powers
of int arrays raise numpy's `ValueError`.

## Layout

- `src/serp_coil.py` — the whole library (pure Serpentine, depends on `serp-math`).
- `tests/test_printing.py` — 50 printing cases, byte-identical to numpy 2.4.6.
- `tests/test_core.py` — arithmetic, broadcasting, dtype promotion, indexing,
  masks, reductions, ufuncs, sorting, stacking, linalg and error wording, also
  byte-identical to numpy under CPython.
