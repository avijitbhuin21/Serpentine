from serp_math import (sqrt, sin, cos, tan, log, exp, pow, floor, ceil, isnan, isinf,
                       pi, e, inf, nan, tau, asin, acos, atan, atan2, sinh, cosh, tanh,
                       asinh, acosh, atanh, cbrt, exp2, expm1, log10, log2, log1p,
                       fabs, copysign, fmod, ldexp, trunc, hypot, nextafter, ulp,
                       degrees, radians, isfinite, isclose, factorial, gcd, lcm,
                       isqrt, comb, perm, frexp, modf, fsum)


def new_surface() -> None:
    print(abs(asin(0.5) - 0.5235987755982989) < 1e-12)
    print(abs(acos(0.5) - 1.0471975511965979) < 1e-12)
    print(abs(atan(1.0) - 0.7853981633974483) < 1e-12)
    print(abs(atan2(1.0, 1.0) - 0.7853981633974483) < 1e-12)
    print(abs(sinh(1.0) - 1.1752011936438014) < 1e-12)
    print(abs(cosh(1.0) - 1.5430806348152437) < 1e-12)
    print(abs(tanh(1.0) - 0.7615941559557649) < 1e-12)
    print(abs(asinh(1.0) - 0.881373587019543) < 1e-12)
    print(abs(acosh(2.0) - 1.3169578969248166) < 1e-12)
    print(abs(atanh(0.5) - 0.5493061443340549) < 1e-12)
    print(abs(cbrt(27.0) - 3.0) < 1e-12)
    print(abs(exp2(10.0) - 1024.0) < 1e-12)
    print(abs(expm1(0.0)) < 1e-12)
    print(abs(log10(1000.0) - 3.0) < 1e-12)
    print(abs(log2(1024.0) - 10.0) < 1e-12)
    print(abs(log1p(0.0)) < 1e-12)
    print(abs(log(8.0, 2.0) - 3.0) < 1e-12)
    print(abs(hypot(3.0, 4.0) - 5.0) < 1e-12)
    print(abs(degrees(pi) - 180.0) < 1e-9)
    print(abs(radians(180.0) - pi) < 1e-12)
    print(tau)
    print(fabs(-3.5))
    print(copysign(3.0, -1.0))
    print(fmod(7.5, 2.0))
    print(ldexp(1.5, 4))
    print(trunc(2.9))
    print(trunc(-2.9))
    print(nextafter(1.0, 2.0))
    print(ulp(1.0))
    print(isfinite(1.0))
    print(isfinite(inf))
    print(isclose(1.0, 1.0))
    print(isclose(1.0, 1.0000000001))
    print(isclose(1.0, 1.1))
    print(isclose(1.0, 1.05, rel_tol=0.1))
    print(isclose(100.0, 100.4, abs_tol=0.5))
    print(factorial(0))
    print(factorial(10))
    print(factorial(20))
    print(gcd(48, 36))
    print(gcd(-48, 36))
    print(lcm(4, 6))
    print(isqrt(0))
    print(isqrt(99))
    print(isqrt(100))
    print(comb(10, 3))
    print(comb(3, 10))
    print(perm(10, 3))
    print(perm(5))
    print(frexp(8.0))
    print(frexp(0.0))
    print(modf(2.75))
    print(modf(-2.75))
    vals: list[float] = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    print(fsum(vals))
    try:
        bad7: float = acos(2.0)
        print(bad7)
    except ValueError as ex7:
        print(f"acos(2): {ex7}")
    try:
        bad8: float = atanh(1.0)
        print(bad8)
    except ValueError as ex8:
        print(f"atanh(1): {ex8}")
    try:
        bad9: float = cosh(10000.0)
        print(bad9)
    except OverflowError as ex9:
        print(f"cosh(1e4): {ex9}")
    try:
        bad10: int = factorial(-1)
        print(bad10)
    except ValueError as ex10:
        print(f"factorial(-1): {ex10}")
    try:
        bad11: int = factorial(21)
        print(bad11)
    except OverflowError as ex11:
        print(f"factorial(21): {ex11}")
    try:
        bad12: int = isqrt(-1)
        print(bad12)
    except ValueError as ex12:
        print(f"isqrt(-1): {ex12}")
    try:
        bad13: float = fmod(1.0, 0.0)
        print(bad13)
    except ValueError as ex13:
        print(f"fmod(1,0): {ex13}")
    try:
        bad14: bool = isclose(1.0, 2.0, rel_tol=-1.0)
        print(bad14)
    except ValueError as ex14:
        print(f"isclose(rel_tol<0): {ex14}")


def main() -> None:
    print(sqrt(2.25))
    print(sqrt(2))
    print(sqrt(0.0))
    print(floor(2.7))
    print(ceil(2.2))
    print(floor(-2.7))
    print(ceil(-2.2))
    print(pi)
    print(e)
    print(inf)
    print(-inf)
    print(isnan(nan))
    print(isnan(1.0))
    print(isinf(inf))
    print(isinf(0.0))
    print(abs(sin(1.0) - 0.8414709848078965) < 1e-12)
    print(abs(cos(1.0) - 0.5403023058681398) < 1e-12)
    print(abs(tan(1.0) - 1.5574077246549023) < 1e-12)
    print(abs(log(e) - 1.0) < 1e-12)
    print(abs(exp(1) - e) < 1e-12)
    print(pow(2.0, 10))
    print(pow(9.0, 0.5))
    try:
        bad: float = sqrt(-1.0)
        print(bad)
    except ValueError as ex:
        print(f"sqrt(-1): {ex}")
    try:
        bad2: float = log(0.0)
        print(bad2)
    except ValueError as ex2:
        print(f"log(0): {ex2}")
    try:
        bad3: float = exp(1000.0)
        print(bad3)
    except OverflowError as ex3:
        print(f"exp(1000): {ex3}")
    try:
        bad4: float = pow(0.0, -1.0)
        print(bad4)
    except ValueError as ex4:
        print(f"pow(0,-1): {ex4}")
    try:
        bad5: int = floor(nan)
        print(bad5)
    except ValueError as ex5:
        print(f"floor(nan): {ex5}")
    try:
        bad6: int = ceil(inf)
        print(bad6)
    except OverflowError as ex6:
        print(f"ceil(inf): {ex6}")
    new_surface()


if __name__ == "__main__":
    main()
