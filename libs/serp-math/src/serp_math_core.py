"""serp-math-core CPython delegate: the native build maps these to runtime primitives.

The Serpentine compiler intercepts `from serp_math_core import ...` (rtlib.py) and
never reads this file; under CPython it delegates to the stdlib `math` module with
the same int64 caps the native runtime enforces, so dual runs stay byte-identical.
"""

import math as _math

_INT64_MAX = (1 << 63) - 1

c_pi = _math.pi
c_e = _math.e
c_tau = _math.tau
c_inf = _math.inf
c_nan = _math.nan

c_sqrt = _math.sqrt
c_sin = _math.sin
c_cos = _math.cos
c_tan = _math.tan
c_log = _math.log
c_exp = _math.exp
c_pow = _math.pow
c_floor = _math.floor
c_ceil = _math.ceil
c_isnan = _math.isnan
c_isinf = _math.isinf
c_isfinite = _math.isfinite
c_acos = _math.acos
c_asin = _math.asin
c_atan = _math.atan
c_atan2 = _math.atan2
c_acosh = _math.acosh
c_asinh = _math.asinh
c_atanh = _math.atanh
c_cosh = _math.cosh
c_sinh = _math.sinh
c_tanh = _math.tanh
c_cbrt = _math.cbrt
c_degrees = _math.degrees
c_radians = _math.radians
c_exp2 = _math.exp2
c_expm1 = _math.expm1
c_fabs = _math.fabs
c_log10 = _math.log10
c_log2 = _math.log2
c_log1p = _math.log1p
c_copysign = _math.copysign
c_fmod = _math.fmod
c_ldexp = _math.ldexp
c_trunc = _math.trunc
c_hypot = _math.hypot
c_nextafter = _math.nextafter
c_ulp = _math.ulp
c_isqrt = _math.isqrt


def c_factorial(n):
    """math.factorial capped at the native int64 width (n <= 20)."""
    if n > 20:
        raise OverflowError("factorial() result exceeds the native int width")
    return _math.factorial(n)


def c_gcd(a, b):
    """math.gcd capped at the native int64 width."""
    r = _math.gcd(a, b)
    if r > _INT64_MAX:
        raise OverflowError("gcd() result exceeds the native int width")
    return r


def c_lcm(a, b):
    """math.lcm capped at the native int64 width."""
    r = _math.lcm(a, b)
    if r > _INT64_MAX:
        raise OverflowError("lcm() result exceeds the native int width")
    return r


def c_comb(n, k):
    """math.comb capped at the native int64 width."""
    r = _math.comb(n, k)
    if r > _INT64_MAX:
        raise OverflowError("comb() result exceeds the native int width")
    return r


def c_perm(n, k):
    """math.perm capped at the native int64 width."""
    r = _math.perm(n, k)
    if r > _INT64_MAX:
        raise OverflowError("perm() result exceeds the native int width")
    return r


def c_frexp_m(x):
    """Mantissa half of math.frexp."""
    return _math.frexp(x)[0]


def c_frexp_e(x):
    """Exponent half of math.frexp."""
    return _math.frexp(x)[1]


def c_modf_frac(x):
    """Fractional half of math.modf."""
    return _math.modf(x)[0]


def c_modf_int(x):
    """Integral half of math.modf."""
    return _math.modf(x)[1]
