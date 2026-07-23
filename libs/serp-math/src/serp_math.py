"""serp-math — drop-in `math` facade over the native runtime core (CPython parity).

Pure Serpentine ([P] over the serp_math_core rtlib module). Function names and
signatures match CPython's `math` module for the surface below. Divergences:
integer results cap at int64 (factorial/comb/perm/gcd/lcm raise OverflowError
past 2**63-1), hypot/dist take exactly two points, gamma/lgamma/erf/erfc/
remainder/prod are not provided yet, and fsum uses exact partials with a
plain final summation.
"""
from __future__ import annotations
from serpentine import Ref
from serp_math_core import (c_pi, c_e, c_tau, c_inf, c_nan, c_sqrt, c_sin, c_cos,
                            c_tan, c_log, c_exp, c_pow, c_floor, c_ceil, c_isnan,
                            c_isinf, c_isfinite, c_acos, c_asin, c_atan, c_atan2,
                            c_acosh, c_asinh, c_atanh, c_cosh, c_sinh, c_tanh,
                            c_cbrt, c_degrees, c_radians, c_exp2, c_expm1, c_fabs,
                            c_log10, c_log2, c_log1p, c_copysign, c_fmod, c_ldexp,
                            c_trunc, c_hypot, c_nextafter, c_ulp, c_factorial,
                            c_gcd, c_lcm, c_isqrt, c_comb, c_perm, c_frexp_m,
                            c_frexp_e, c_modf_frac, c_modf_int)

pi: float = c_pi
e: float = c_e
tau: float = c_tau
inf: float = c_inf
nan: float = c_nan


def sqrt(x: float) -> float:
    return c_sqrt(x)


def sin(x: float) -> float:
    return c_sin(x)


def cos(x: float) -> float:
    return c_cos(x)


def tan(x: float) -> float:
    return c_tan(x)


def asin(x: float) -> float:
    return c_asin(x)


def acos(x: float) -> float:
    return c_acos(x)


def atan(x: float) -> float:
    return c_atan(x)


def atan2(y: float, x: float) -> float:
    return c_atan2(y, x)


def asinh(x: float) -> float:
    return c_asinh(x)


def acosh(x: float) -> float:
    return c_acosh(x)


def atanh(x: float) -> float:
    return c_atanh(x)


def sinh(x: float) -> float:
    return c_sinh(x)


def cosh(x: float) -> float:
    return c_cosh(x)


def tanh(x: float) -> float:
    return c_tanh(x)


def cbrt(x: float) -> float:
    return c_cbrt(x)


def exp(x: float) -> float:
    return c_exp(x)


def exp2(x: float) -> float:
    return c_exp2(x)


def expm1(x: float) -> float:
    return c_expm1(x)


def log(x: float, base: float | None = None) -> float:
    if base is None:
        return c_log(x)
    return c_log(x) / c_log(base)


def log10(x: float) -> float:
    return c_log10(x)


def log2(x: float) -> float:
    return c_log2(x)


def log1p(x: float) -> float:
    return c_log1p(x)


def pow(x: float, y: float) -> float:
    return c_pow(x, y)


def floor(x: float) -> int:
    return c_floor(x)


def ceil(x: float) -> int:
    return c_ceil(x)


def trunc(x: float) -> int:
    return c_trunc(x)


def fabs(x: float) -> float:
    return c_fabs(x)


def copysign(x: float, y: float) -> float:
    return c_copysign(x, y)


def fmod(x: float, y: float) -> float:
    return c_fmod(x, y)


def ldexp(x: float, i: int) -> float:
    return c_ldexp(x, i)


def hypot(x: float, y: float) -> float:
    return c_hypot(x, y)


def nextafter(x: float, y: float) -> float:
    return c_nextafter(x, y)


def ulp(x: float) -> float:
    return c_ulp(x)


def degrees(x: float) -> float:
    return c_degrees(x)


def radians(x: float) -> float:
    return c_radians(x)


def isnan(x: float) -> bool:
    return c_isnan(x)


def isinf(x: float) -> bool:
    return c_isinf(x)


def isfinite(x: float) -> bool:
    return c_isfinite(x)


def isclose(a: float, b: float, rel_tol: float = 1e-09, abs_tol: float = 0.0) -> bool:
    if rel_tol < 0.0 or abs_tol < 0.0:
        raise ValueError("tolerances must be non-negative")
    if a == b:
        return True
    if c_isinf(a) or c_isinf(b):
        return False
    diff: float = abs(b - a)
    if diff <= abs(rel_tol * b):
        return True
    if diff <= abs(rel_tol * a):
        return True
    return diff <= abs_tol


def factorial(n: int) -> int:
    return c_factorial(n)


def gcd(a: int, b: int) -> int:
    return c_gcd(a, b)


def lcm(a: int, b: int) -> int:
    return c_lcm(a, b)


def isqrt(n: int) -> int:
    return c_isqrt(n)


def comb(n: int, k: int) -> int:
    return c_comb(n, k)


def perm(n: int, k: int | None = None) -> int:
    if k is None:
        return c_perm(n, n)
    return c_perm(n, k)


def frexp(x: float) -> tuple[float, int]:
    return (c_frexp_m(x), c_frexp_e(x))


def modf(x: float) -> tuple[float, float]:
    return (c_modf_frac(x), c_modf_int(x))


def fsum(seq: Ref[list[float]]) -> float:
    partials: list[float] = []
    special: float = 0.0
    has_special: bool = False
    for idx in range(len(seq)):
        x: float = seq[idx]
        if c_isnan(x) or c_isinf(x):
            special += x
            has_special = True
            continue
        i: int = 0
        for j in range(len(partials)):
            y: float = partials[j]
            if abs(x) < abs(y):
                t: float = x
                x = y
                y = t
            hi: float = x + y
            lo: float = y - (hi - x)
            if lo != 0.0:
                partials[i] = lo
                i += 1
            x = hi
        while len(partials) > i:
            partials.pop()
        partials.append(x)
    if has_special:
        return special
    total: float = 0.0
    for k2 in range(len(partials)):
        total += partials[k2]
    return total
