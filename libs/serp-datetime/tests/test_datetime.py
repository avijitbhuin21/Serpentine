from serp_datetime import (Dt, make, make_date, is_leap, days_in_month,
                           to_unix, from_unix, now_utc, weekday, day_of_year,
                           add_days, add_seconds, diff_seconds, iso_format,
                           parse_iso, date, datetime, timedelta, utcnow,
                           MINYEAR, MAXYEAR)


def objects_section() -> None:
    td = timedelta(days=1, hours=25, minutes=-90, seconds=3, milliseconds=1500,
                   microseconds=250)
    print(td.days, td.seconds, td.microseconds)
    print(td.total_seconds())
    neg = -td
    print(neg.days, neg.seconds, neg.microseconds)
    tsum = td + timedelta(weeks=1)
    print(tsum.days, tsum.seconds)
    tmul = timedelta(hours=1, microseconds=7) * 25
    print(tmul.days, tmul.seconds, tmul.microseconds)
    print(td < tsum, td >= tsum, timedelta(1) == timedelta(days=1))

    d1 = date(2024, 2, 29)
    print(d1.year, d1.month, d1.day)
    print(d1.isoformat(), d1.toordinal(), d1.weekday(), d1.isoweekday())
    d2 = d1 + timedelta(days=366)
    print(d2.isoformat())
    dd = d2 - d1
    print(dd.days)
    print(d1 < d2, d1 >= d2, d1 == date(2024, 2, 29))
    print(d1.replace(year=2020).isoformat(), d1.replace(month=3, day=1).isoformat())
    print(date(MINYEAR, 1, 1).isoformat(), date(MAXYEAR, 12, 31).isoformat())
    try:
        bad1 = date(2021, 2, 29)
        print(bad1.isoformat())
    except ValueError as e:
        print("caught:", e)
    try:
        bad2 = date(2020, 13, 1)
        print(bad2.isoformat())
    except ValueError as e:
        print("caught:", e)
    try:
        bad3 = date(0, 1, 1)
        print(bad3.isoformat())
    except ValueError as e:
        print("caught:", e)

    t1 = datetime(2026, 7, 22, 14, 30, 5)
    print(t1.isoformat(), t1.weekday())
    t2 = datetime(2026, 7, 22, 14, 30, 5, 123456)
    print(t2.isoformat(), t2.isoformat(" "))
    t3 = t1 + timedelta(days=-3, hours=50, microseconds=999999)
    print(t3.isoformat())
    dt3 = t3 - t1
    print(dt3.days, dt3.seconds, dt3.microseconds)
    print(t1 < t3, t1 >= t3, t1 == datetime(2026, 7, 22, 14, 30, 5))
    print(t2.date().isoformat())
    try:
        bad4 = datetime(2020, 1, 1, 24)
        print(bad4.isoformat())
    except ValueError as e:
        print("caught:", e)
    try:
        bad5 = datetime(2020, 1, 1, 0, 0, 0, 1000000)
        print(bad5.isoformat())
    except ValueError as e:
        print("caught:", e)
    nowd = utcnow()
    print(nowd.year >= 2026)
    print(date.fromisoformat("2024-02-29").isoformat())
    print(datetime.fromisoformat("2026-07-22T14:30:05").isoformat())
    print(datetime.fromisoformat("2026-07-22 14:30").isoformat())
    print(datetime.fromisoformat("2026-07-22T14:30:05.5Z").isoformat())
    print(datetime.fromisoformat("2026-07-22").isoformat())
    print(datetime.fromtimestamp(0.0).isoformat())
    isobad: list[str] = ["2026-07", "2026-7-22", "2026-07-22T14",
                         "2026-07-22T14:30:05+01:00", "2026-07-22T14:30:05.1234567"]
    for s in isobad:
        try:
            print(datetime.fromisoformat(s).isoformat())
        except ValueError as e6:
            print("caught:", e6)
    try:
        print(date.fromisoformat("2026-07-22T14:30").isoformat())
    except ValueError as e7:
        print("caught:", e7)
    print(d1)
    print(str(d2), f"day={d1}")
    print(t1)
    print(t2)
    print(str(t2.date()))
    print(td)
    print(-td)
    print(timedelta(days=1))
    print(timedelta(days=-1, seconds=1))
    print(timedelta(days=2, hours=3, microseconds=7))
    print(timedelta())
    print(f"{dd} / {t1 - t2}")
    print(f"{d1!r}")
    print(f"{t1!r} {t2!r}")
    print(f"{datetime(2020, 5, 6)!r}")
    print(f"{td!r} {timedelta()!r} {timedelta(days=-1, seconds=1)!r}")
    print([date(2024, 2, 29), date(2025, 3, 2)])
    print([t1 - t1, timedelta(milliseconds=1)])


def main() -> None:
    print(is_leap(2000), is_leap(1900), is_leap(2024), is_leap(2026))
    print(days_in_month(2024, 2), days_in_month(2026, 2), days_in_month(2026, 7))
    epoch: Dt = make(1970, 1, 1, 0, 0, 0)
    print(to_unix(epoch), weekday(epoch), iso_format(epoch))
    dt: Dt = make(2026, 7, 21, 14, 30, 5)
    print(iso_format(dt), to_unix(dt), weekday(dt), day_of_year(dt))
    rt: Dt = from_unix(to_unix(dt))
    print(iso_format(rt) == iso_format(dt))
    print(iso_format(from_unix(0)), iso_format(from_unix(-1)), iso_format(from_unix(1000000000)))
    leap_day: Dt = make_date(2024, 2, 29)
    print(iso_format(leap_day), weekday(leap_day))
    print(iso_format(add_days(leap_day, 1)), iso_format(add_days(leap_day, -1)))
    print(iso_format(add_days(dt, 365)))
    print(iso_format(add_seconds(dt, 3600)), iso_format(add_seconds(dt, -86400)))
    later: Dt = make(2026, 7, 22, 14, 30, 5)
    print(diff_seconds(later, dt))
    p1: Dt = parse_iso("2026-07-21")
    p2: Dt = parse_iso("2026-07-21T14:30:05")
    p3: Dt = parse_iso("2026-07-21 14:30:05")
    print(iso_format(p1), iso_format(p2), iso_format(p3))
    print(iso_format(parse_iso("0001-01-01")))
    bad: list[str] = ["2026-13-01", "2026-02-30", "not-a-date", "2026-07-21T25:00:00",
                      "2026-07", "2026-07-21Tab:cd:ef"]
    for s in bad:
        try:
            print(iso_format(parse_iso(s)))
        except ValueError as e:
            print("caught:", e)
    now: Dt = now_utc()
    print(now.year >= 2026, now.year < 2100, 1 <= now.month, now.month <= 12)
    objects_section()


if __name__ == "__main__":
    main()
