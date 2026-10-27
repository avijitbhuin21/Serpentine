# serp-bigint

Arbitrary-precision integers for [Serpentine](https://github.com/avijitbhuin21/Serpentine), where
the built-in `int` is int64 (with an `OverflowError` trap).

```python
from serp_bigint import BigInt, big

f = big(1)
for i in range(2, 101):
    f = f * big(i)
print(f)                         # 100! — all 158 digits
print(big(2) ** 200 // big(3))  # floor division, Python semantics
```

`+ - * // % **`, unary `-`, `abs()`, comparisons, `divmod` (`bigdivmod`), `str`/`repr`,
`BigInt.parse("…")`, `big(int)` and `to_int()`. Results match CPython's unbounded `int`
(37,854 randomized checks).
