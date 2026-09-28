"""Core semantics: construction, arithmetic + broadcasting, dtype promotion, indexing, masks,
reductions, ufuncs, sorting, stacking, linear algebra and numpy-worded errors."""
from serp_coil import (allclose, arange, argmax, argmax_axis, argmin, argsort, around, array,
                       array_equal, clip, column, concatenate, count_nonzero, cumsum, cumsum_axis,
                       det, diag, diff, dot, exp, extract, eye, flatnonzero, floor, full, hstack,
                       inv, isnan, linspace, log, matmul, max_axis, maximum, mean, mean_axis, median,
                       minimum, nan, ndarray, norm, ones, outer, percentile, power, row, searchsorted,
                       sign, slice_, solve, sort, sqrt, std, std_axis, sum, sum_axis, take, trace,
                       transpose, unique, var, vdot, vstack, where, zeros, zeros_like, tile, repeat,
                       logical_and, logical_not, average, prod, all_axis, any_axis, ptp, mod, sin,
                       float64, int64, bool_)
from serpentine import Ref


def show(a: Ref[ndarray]) -> None:
    print(f"{a!r}")


def main() -> None:
    a = array([1, 2, 3])
    b = array([1.5, 2.5, 3.5])
    show(a + b)
    show(a - 1)
    show(a * 2)
    show(a * 2.5)
    show(2 * a)
    show(10 - a)
    show(a / 2)
    show(1 / b)
    show(a // 2)
    show(a % 2)
    show(a ** 2)
    show(2 ** a)
    show(b ** 0.5)
    show(-a)
    show(a + a)
    print(a.dtype, b.dtype, (a + b).dtype, (a / 2).dtype, (a < 2).dtype)
    m = array([[1, 2, 3], [4, 5, 6]])
    show(m + a)
    show(m * array([[10], [100]]))
    show(m.T)
    show(transpose(m) @ m)
    show(m @ a)
    show(dot(a, a))
    print(vdot(a, a), a.dot(b).item())
    show(outer(a, array([1, 10])))
    print(m.shape, m.ndim, m.size, len(m), a.shape)
    print(m[0, 1], m[1, -1], a[-1], a[0])
    c = zeros(4)
    c[0] = 1
    c[1] = 2.5
    c[-1] = -3
    show(c)
    m2 = zeros((2, 2), dtype=int64)
    m2[0, 0] = 7
    m2[1, 1] = 9
    show(m2)
    mask = a > 1
    show(mask)
    show(a == 2)
    show(a != 2)
    show((a > 1) & (a < 3))
    show((a < 2) | (a > 2))
    show(~mask)
    show(extract(mask, a))
    c2 = arange(6)
    c2[c2 % 2 == 0] = -1
    show(c2)
    show(where(a > 1, a, 0))
    show(where(a > 1, 1.5, -1.5))
    show(where(m > 2, m, array([100, 200, 300])))
    print(a.sum(), sum(a), a.mean(), a.prod(), a.min(), a.max(), argmin(a), argmax(b))
    print(mean(b), var(b), std(b), b.var(ddof=1), b.std(ddof=1))
    print(median(array([3, 1, 2])), median(array([4, 1, 2, 3])), percentile(arange(11), 25))
    print(average(b), average(b, array([1, 1, 2])))
    show(sum_axis(m, 0))
    show(sum_axis(m, 1))
    show(mean_axis(m, 0))
    show(max_axis(m, 1))
    show(argmax_axis(m, 0))
    show(std_axis(m, 1))
    show(cumsum(a))
    show(cumsum_axis(m, 1))
    show(all_axis(m > 3, 1))
    show(any_axis(m > 3, 1))
    print(count_nonzero(mask), ptp(a), prod(b))
    show(flatnonzero(array([0, 3, 0, 5])))
    show(sqrt(array([4, 9, 2])))
    show(exp(array([0, 1])))
    show(log(array([1.0, e_val(), 0.0, -1.0])))
    show(sin(linspace(0, 3.141592653589793, 3)))
    show(floor(array([1.5, -1.5, 2.0])))
    show(around(array([0.5, 1.5, 2.5, -0.5, 1.2345]), 0))
    show(around(array([1.2345, 2.5678]), 2))
    show(sign(array([-2.0, 0.0, 3.0])))
    show(clip(arange(6), 1, 4))
    show(maximum(a, array([2, 0, 5])))
    show(minimum(a, 2))
    show(power(a, 3))
    show(mod(array([5.5, -5.5]), 2))
    show(isnan(array([1.0, nan])))
    show(logical_and(a > 1, a < 3))
    show(logical_not(mask))
    show(sort(array([3.0, 1.0, nan, 2.0])))
    show(argsort(array([30, 10, 20])))
    show(unique(array([3, 1, 2, 3, 1])))
    print(searchsorted(array([1, 3, 5, 7]), 4))
    show(concatenate(a, b))
    show(vstack(a, b))
    show(hstack(m, m))
    show(concatenate(m, m, axis=1))
    show(take(a, [2, 0]))
    show(row(m, 1))
    show(column(m, 2))
    show(slice_(arange(10), 2, 8, 3))
    show(slice_(arange(5), -3, 5))
    show(repeat(a, 2))
    show(tile(a, 2))
    show(diff(array([1, 4, 9, 16])))
    show(full((2, 2), 7))
    show(full(3, 2.5))
    show(ones(2, dtype=bool_))
    show(zeros_like(m))
    show(eye(2, 3))
    show(eye(3, k=1))
    show(diag(m))
    show(diag(array([1, 2])))
    print(trace(array([[1.0, 2.0], [3.0, 4.0]])))
    sq = array([[4.0, 7.0], [2.0, 6.0]])
    print(round(det(sq), 6))
    show(inv(sq))
    show(solve(sq, array([1.0, 2.0])))
    print(norm(array([3.0, 4.0])))
    print(array_equal(a, array([1, 2, 3])), array_equal(a, b), allclose(a, a + 1e-9))
    show(a.astype(float64))
    show(b.astype(int64))
    show(array([0, 1, 2]).astype(bool_))
    show(array([1, 2, 3, 4, 5, 6]).reshape((2, 3)))
    show(arange(6).reshape([3, -1]))
    show(m.flatten())
    show(matmul(eye(2), array([[1.0, 2.0], [3.0, 4.0]])))
    show(arange(0, 1, 0.25))
    show(arange(5, 0, -2))
    show(arange(3, dtype=float64))
    show(linspace(1, 2, 3, endpoint=False))
    total: float = 0.0
    for x in a:
        total = total + x
    print(total, a.tolist(), a.item(1))
    try:
        show(a + array([1, 2]))
    except ValueError as err:
        print("ValueError:", err)
    try:
        print(a[3])
    except IndexError as err2:
        print("IndexError:", err2)
    try:
        show(a.reshape((2, 2)))
    except ValueError as err3:
        print("ValueError:", err3)
    try:
        show(m @ m)
    except ValueError as err4:
        print("ValueError:", err4)
    try:
        show(array([[1, 2], [3]]))
    except ValueError as err5:
        print("ValueError:", err5)


def e_val() -> float:
    return 2.718281828459045


if __name__ == "__main__":
    main()
