# serp-statistics

Drop-in facade for CPython's `statistics` module, written in the Serpentine
subset: the same source compiles to native code with `serp` and imports under
CPython.

## API (data is `list[float]`)

- `mean`, `fmean`, `geometric_mean`, `harmonic_mean`
- `median`, `median_low`, `median_high`
- `variance` / `stdev` (sample, n-1), `pvariance` / `pstdev` (population)
- `covariance(x, y)`, `correlation(x, y)`
- `quantiles(xs, n=4, method="exclusive")` — "inclusive" also supported.
- `StatisticsError` (ValueError subclass) with CPython's messages.

Divergences: mean/variance use float arithmetic (CPython uses exact rationals
internally — last-ulp differences possible); mode/multimode/median_grouped/
NormalDist are not provided. Depends on `serp-math`.

## Install

```
serp add serp-statistics
pip install serp-statistics
```
