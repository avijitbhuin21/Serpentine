from serp_statistics import (mean, median, median_low, median_high,
                             variance, pvariance, stdev, pstdev, quantiles,
                             fmean, geometric_mean, harmonic_mean,
                             covariance, correlation, StatisticsError)


def new_surface() -> None:
    ys: list[float] = [1.0, 2.0, 3.0, 4.0]
    print(fmean(ys))
    print(geometric_mean([1.0, 4.0, 16.0]) )
    print(harmonic_mean([2.0, 3.0, 6.0]))
    print(harmonic_mean([2.0, 0.0, 6.0]))
    a: list[float] = [1.0, 2.0, 3.0, 4.0, 5.0]
    b: list[float] = [2.0, 4.0, 6.0, 8.0, 10.0]
    print(covariance(a, b))
    print(correlation(a, b))
    print(quantiles(ys, n=4, method="inclusive"))
    print(quantiles(ys, method="inclusive", n=2))
    empty2: list[float] = []
    try:
        print(fmean(empty2))
    except StatisticsError as e:
        print("caught:", e)
    try:
        print(geometric_mean([1.0, -2.0]))
    except StatisticsError as e2:
        print("caught:", e2)
    try:
        print(harmonic_mean([1.0, -2.0]))
    except StatisticsError as e3:
        print("caught:", e3)
    try:
        print(correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]))
    except StatisticsError as e4:
        print("caught:", e4)
    try:
        print(covariance([1.0, 2.0], [1.0, 2.0, 3.0]))
    except StatisticsError as e5:
        print("caught:", e5)
    try:
        print(quantiles(ys, n=4, method="middle"))
    except ValueError as e6:
        print("caught:", e6)


def main() -> None:
    xs: list[float] = [2.75, 1.75, 1.25, 0.25, 0.5, 1.25, 3.5]
    print(mean(xs))
    print(median(xs))
    print(median_low(xs))
    print(median_high(xs))
    ys: list[float] = [1.0, 2.0, 3.0, 4.0]
    print(mean(ys), median(ys), median_low(ys), median_high(ys))
    print(variance(ys))
    print(pvariance(ys))
    print(stdev(ys))
    print(pstdev(ys))
    print(quantiles(xs))
    print(quantiles(ys, 2))
    print(quantiles(ys, 10))
    empty: list[float] = []
    try:
        print(mean(empty))
    except ValueError as e:
        print("caught:", e)
    one: list[float] = [5.0]
    try:
        print(variance(one))
    except ValueError as e:
        print("caught:", e)
    try:
        print(quantiles(one))
    except ValueError as e:
        print("caught:", e)
    new_surface()


if __name__ == "__main__":
    main()
