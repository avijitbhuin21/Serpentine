from serp_time import (time, monotonic, sleep, time_ns, monotonic_ns,
                       perf_counter, perf_counter_ns)


def main() -> None:
    t: float = time()
    print(t > 1000000000.0)
    m0: float = monotonic()
    sleep(0.0)
    sleep(0.01)
    m1: float = monotonic()
    print(m1 >= m0)
    print(m1 - m0 >= 0.0)
    print(m1 - m0 < 60.0)
    print(time_ns() > 1000000000000000000)
    n0: int = monotonic_ns()
    sleep(0.001)
    n1: int = monotonic_ns()
    print(n1 >= n0)
    p0: float = perf_counter()
    sleep(0.001)
    p1: float = perf_counter()
    print(p1 >= p0)
    q0: int = perf_counter_ns()
    sleep(0.001)
    q1: int = perf_counter_ns()
    print(q1 >= q0)
    try:
        sleep(-1.0)
    except ValueError as ex:
        print(f"sleep(-1): {ex}")


if __name__ == "__main__":
    main()
