from serp_datetime import datetime, timedelta, timezone, UTC


def main() -> None:
    utc = timezone.utc
    print(utc, f"{utc!r}", utc.tzname(None), utc.utcoffset(None))
    print(UTC == timezone.utc, f"{UTC!r}")
    ist = timezone(timedelta(hours=5, minutes=30))
    est = timezone(timedelta(hours=-5), "EST")
    odd = timezone(timedelta(hours=1, seconds=7))
    print(ist, est, odd)
    print(f"{ist!r}", f"{est!r}")
    print(ist.utcoffset(None), est.utcoffset(None))
    print(ist == timezone(timedelta(minutes=330)), ist == est)
    try:
        bad = timezone(timedelta(hours=24))
        print(bad)
    except ValueError as e:
        print("caught:", e)

    a = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    print(a, a.isoformat(), f"{a!r}")
    print(a.utcoffset(), a.tzname())
    b = a.astimezone(ist)
    print(b, b.tzname(), f"{b!r}")
    c = a.astimezone(est)
    print(c.isoformat(), c.tzname())
    print(a == b, b == c, a < b, a <= c, b > c, a >= c)
    print(b - c, a - c)
    d = b + timedelta(hours=20)
    print(d, d.tzname())
    print(a.timestamp(), b.timestamp())
    print(datetime.fromtimestamp(1700000000.5, timezone(timedelta(hours=5, minutes=30))))
    print(datetime.fromtimestamp(0.0, timezone.utc).isoformat())

    naive = datetime(2026, 3, 1, 12, 0)
    print(naive.utcoffset(), naive.tzname(), naive == a)
    try:
        print(naive < a)
    except TypeError as e2:
        print("caught:", e2)
    try:
        print(a - naive)
    except TypeError as e3:
        print("caught:", e3)

    for s in ["2026-07-22T14:30:05Z", "2026-07-22T14:30:05+01:00",
              "2026-07-22T14:30:05.25-08:00", "2026-07-22 14:30+0530",
              "2026-07-22T14:30:05+05:30:15", "2026-07-22T14:30:05.5+00:00"]:
        p = datetime.fromisoformat(s)
        print(p.isoformat(), p.tzname(), f"{p.utcoffset()!r}")
    for s2 in ["2026-07-22T14:30:05+1:00", "2026-07-22T14:30:05+01:0x"]:
        try:
            print(datetime.fromisoformat(s2))
        except ValueError as e4:
            print("caught:", e4)

    r = b.replace(hour=1, minute=2)
    print(r, r.tzname())
    n = datetime.now(timezone.utc)
    print(n.tzname(), n.year >= 2026)
    print(datetime.now(tz=timezone(timedelta(hours=-3))).utcoffset())
    print([a.astimezone(timezone.utc), b.replace()])


if __name__ == "__main__":
    main()
