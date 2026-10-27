from __future__ import annotations

from serp_prometheus import (CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Summary,
                             generate_latest)
from serpentine import spawn

REQUESTS = Counter("http_requests_total", "Total HTTP requests.", ["method", "status"])
INFLIGHT = Gauge("inflight_requests", "Requests being served.")
LATENCY = Histogram("request_seconds", "Request latency.", buckets=[0.01, 0.1, 1.0])


def worker(n: int) -> int:
    """Increment shared metrics from another thread."""
    i: int = 0
    while i < n:
        REQUESTS.labels("GET", "200").inc()
        i += 1
    return n


def main() -> None:
    print(CONTENT_TYPE_LATEST)
    REQUESTS.labels("GET", "200").inc()
    REQUESTS.labels("POST", "201").inc(2.5)
    INFLIGHT.inc()
    INFLIGHT.inc(3.0)
    INFLIGHT.dec()
    LATENCY.observe(0.005)
    LATENCY.observe(0.05)
    LATENCY.observe(3.0)
    jobs = Summary("job_seconds", "Job runtime\nin seconds.", ["queue"])
    jobs.labels("a\"b").observe(1.25)
    errors = Counter("errors", "Errors by kind.")
    errors.inc()

    h1 = spawn(worker, 500)
    h2 = spawn(worker, 500)
    print(h1.join() + h2.join())
    print(REQUESTS.labels("GET", "200").get(), INFLIGHT.get())
    INFLIGHT.set(7.0)

    text: str = generate_latest().decode("utf-8")
    print(text[0:len(text) - 1])

    try:
        REQUESTS.inc()
    except ValueError as e:
        print("caught:", e)
    try:
        REQUESTS.labels("GET").inc()
    except ValueError as e2:
        print("caught:", e2)
    try:
        errors.inc(-1.0)
    except ValueError as e3:
        print("caught:", e3)
    try:
        bad = Histogram("bad_hist", "x", buckets=[1.0, 0.5])
        bad.observe(1.0)
    except ValueError as e4:
        print("caught:", e4)
    try:
        clash = Gauge("errors", "same name, other type")
        clash.set(1.0)
    except ValueError as e5:
        print("caught:", e5)


if __name__ == "__main__":
    main()
