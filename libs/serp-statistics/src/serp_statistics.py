"""serp-statistics — drop-in `statistics` facade in the Serpentine subset.

Pure Serpentine ([P]): the same source compiles natively and runs under
CPython. Operates on list[float]. Divergences: mean/variance use float
arithmetic (CPython uses exact rationals internally, so results can differ
in the last ulp), mode/multimode/median_grouped/NormalDist are not provided.
"""
from __future__ import annotations
from serpentine import Ref
from serp_math import sqrt, fsum, log, exp


class StatisticsError(ValueError):
    pass


def mean(xs: Ref[list[float]]) -> float:
    if len(xs) == 0:
        raise StatisticsError("mean requires at least one data point")
    return sum(xs) / len(xs)


def fmean(xs: Ref[list[float]]) -> float:
    if len(xs) == 0:
        raise StatisticsError("fmean requires at least one data point")
    return fsum(xs) / len(xs)


def geometric_mean(xs: Ref[list[float]]) -> float:
    logs: list[float] = []
    try:
        for i in range(len(xs)):
            logs.append(log(xs[i]))
        return exp(fmean(logs))
    except ValueError:
        raise StatisticsError("geometric mean requires a non-empty dataset containing positive numbers")


def harmonic_mean(xs: Ref[list[float]]) -> float:
    n: int = len(xs)
    if n < 1:
        raise StatisticsError("harmonic_mean requires at least one data point")
    recips: list[float] = []
    for i in range(n):
        x: float = xs[i]
        if x < 0.0:
            raise StatisticsError("harmonic mean does not support negative values")
        if x == 0.0:
            return 0.0
        recips.append(1.0 / x)
    return n / fsum(recips)


def median(xs: Ref[list[float]]) -> float:
    n: int = len(xs)
    if n == 0:
        raise StatisticsError("no median for empty data")
    data: list[float] = sorted(xs)
    if n % 2 == 1:
        return data[n // 2]
    lo: float = data[n // 2 - 1]
    hi: float = data[n // 2]
    return (lo + hi) / 2.0


def median_low(xs: Ref[list[float]]) -> float:
    n: int = len(xs)
    if n == 0:
        raise StatisticsError("no median for empty data")
    data: list[float] = sorted(xs)
    if n % 2 == 1:
        return data[n // 2]
    return data[n // 2 - 1]


def median_high(xs: Ref[list[float]]) -> float:
    n: int = len(xs)
    if n == 0:
        raise StatisticsError("no median for empty data")
    data: list[float] = sorted(xs)
    return data[n // 2]


def _sumsq_dev(xs: Ref[list[float]], mu: float) -> float:
    total: float = 0.0
    for x in xs:
        d: float = x - mu
        total += d * d
    return total


def pvariance(xs: Ref[list[float]]) -> float:
    if len(xs) == 0:
        raise StatisticsError("pvariance requires at least one data point")
    mu: float = mean(xs)
    return _sumsq_dev(xs, mu) / len(xs)


def variance(xs: Ref[list[float]]) -> float:
    if len(xs) < 2:
        raise StatisticsError("variance requires at least two data points")
    mu: float = mean(xs)
    return _sumsq_dev(xs, mu) / (len(xs) - 1)


def pstdev(xs: Ref[list[float]]) -> float:
    return sqrt(pvariance(xs))


def stdev(xs: Ref[list[float]]) -> float:
    return sqrt(variance(xs))


def covariance(x: Ref[list[float]], y: Ref[list[float]]) -> float:
    n: int = len(x)
    if len(y) != n:
        raise StatisticsError("covariance requires that both inputs have same number of data points")
    if n < 2:
        raise StatisticsError("covariance requires at least two data points")
    xbar: float = fsum(x) / n
    ybar: float = fsum(y) / n
    prods: list[float] = []
    for i in range(n):
        prods.append((x[i] - xbar) * (y[i] - ybar))
    return fsum(prods) / (n - 1)


def correlation(x: Ref[list[float]], y: Ref[list[float]]) -> float:
    n: int = len(x)
    if len(y) != n:
        raise StatisticsError("correlation requires that both inputs have same number of data points")
    if n < 2:
        raise StatisticsError("correlation requires at least two data points")
    xbar: float = fsum(x) / n
    ybar: float = fsum(y) / n
    sxy_l: list[float] = []
    sxx_l: list[float] = []
    syy_l: list[float] = []
    for i in range(n):
        dx: float = x[i] - xbar
        dy: float = y[i] - ybar
        sxy_l.append(dx * dy)
        sxx_l.append(dx * dx)
        syy_l.append(dy * dy)
    denom: float = sqrt(fsum(sxx_l) * fsum(syy_l))
    if denom == 0.0:
        raise StatisticsError("at least one of the inputs is constant")
    return fsum(sxy_l) / denom


def quantiles(xs: Ref[list[float]], n: int = 4, method: str = "exclusive") -> list[float]:
    if n < 1:
        raise StatisticsError("n must be at least 1")
    ld: int = len(xs)
    if ld < 2:
        raise StatisticsError("must have at least two data points")
    data: list[float] = sorted(xs)
    result: list[float] = []
    if method == "inclusive":
        m2: int = ld - 1
        for i2 in range(1, n):
            j2: int = (i2 * m2) // n
            delta2: int = i2 * m2 - j2 * n
            interp2: float = (data[j2] * (n - delta2) + data[j2 + 1] * delta2) / n
            result.append(interp2)
        return result
    if method != "exclusive":
        raise ValueError(f"Unknown method: '{method}'")
    m: int = ld + 1
    for i in range(1, n):
        j: int = (i * m) // n
        if j < 1:
            j = 1
        elif j > ld - 1:
            j = ld - 1
        delta: int = i * m - j * n
        interpolated: float = (data[j - 1] * (n - delta) + data[j] * delta) / n
        result.append(interpolated)
    return result
