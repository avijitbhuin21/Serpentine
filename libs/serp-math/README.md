# serp-math

Drop-in replacement for CPython's `math` module (docs/libraries.md drop-in facade push).

- 60+ stdlib-identical names: trig/hyperbolic (`sin..atanh`), exp/log families
  (`exp/exp2/expm1/log/log10/log2/log1p`, `log(x, base)` supported), `sqrt/cbrt/pow`,
  rounding (`floor/ceil/trunc`), float helpers (`fabs/copysign/fmod/ldexp/frexp/modf/
  nextafter/ulp/hypot`), predicates (`isnan/isinf/isfinite/isclose` with
  `rel_tol`/`abs_tol` kwargs), integer functions (`factorial/gcd/lcm/isqrt/comb/perm`),
  `fsum`, and constants `pi/e/tau/inf/nan`.
- Architecture: `serp_math` is a pure-Serpentine facade over the compiler-known
  `serp_math_core` rtlib module (runtime primitives in rt.rs/prelude.rs with
  CPython-parity errors: `ValueError("math domain error")`,
  `OverflowError("math range error")`).
- Divergences: integer results cap at int64 (`factorial` > 20, huge `comb`/`perm`/
  `lcm` raise OverflowError); `gamma/lgamma/erf/erfc/remainder/prod/dist` are not
  provided yet; `hypot` takes exactly two coordinates.

Install into a Serpentine project with `serp add serp-math`.
