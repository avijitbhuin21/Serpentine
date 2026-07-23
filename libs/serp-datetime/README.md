# serp-datetime

UTC date/time written in the Serpentine subset, over `serp-time` for the
clock. `Dt` is a year/month/day/hour/minute/second dataclass — UTC only,
second resolution; timezones (zoneinfo) come later per the roadmap.

## API

- `make(y, mo, d, h, mi, s)` / `make_date(y, mo, d)` — validated
  construction (`ValueError` with CPython-style messages).
- `now_utc()` — current UTC time via `serp_time.time()`.
- `to_unix(dt) -> int` / `from_unix(ts) -> Dt` — proleptic Gregorian,
  days-from-civil algorithm (valid for any year).
- `iso_format(dt)` — `YYYY-MM-DDTHH:MM:SS`; `parse_iso(s)` accepts a date or
  date`T`time (space separator ok).
- `weekday(dt)` — 0 = Monday; `day_of_year(dt)`; `is_leap(y)`;
  `days_in_month(y, m)`.
- `add_days(dt, n)`, `add_seconds(dt, n)`, `diff_seconds(a, b)` —
  timedelta-style arithmetic.

## Install

```
serp add serp-datetime
pip install serp-datetime
```
