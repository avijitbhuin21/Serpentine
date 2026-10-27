"""serp-datetime — date/datetime/timedelta objects plus UTC helpers.

Pure Serpentine ([P]) over serp-time for the clock. date/datetime/timedelta
are real classes mirroring the stdlib constructors: __post_init__ validation
(messages pinned to CPython 3.11), timedelta keyword args normalize exactly
like CPython, stdlib field names, comparisons, +/- arithmetic, isoformat(),
str() and repr() parity, and datetime.utcnow(). Caps: timedelta additionally
exposes zeroed milliseconds/minutes/hours/weeks fields (normalization
happens in __post_init__), int-only timedelta arguments, one __sub__ per
class (subtract a timedelta by adding its negation), no strftime/timezones/
local-time today()/now(). Dt is the original plain UTC helper dataclass.
"""
from __future__ import annotations
from serpentine import Mut, Ref, Owned, dataclass, move
from serp_time import time

DAYS_TO_UNIX: int = 719468
SECS_PER_DAY: int = 86400


@dataclass
class Dt:
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int


def is_leap(year: int) -> bool:
    if year % 4 != 0:
        return False
    if year % 100 != 0:
        return True
    return year % 400 == 0


def days_in_month(year: int, month: int) -> int:
    if month < 1 or month > 12:
        raise ValueError(f"month must be in 1..12, got {month}")
    lengths: list[int] = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if month == 2 and is_leap(year):
        return 29
    return lengths[month - 1]


def make(year: int, month: int, day: int, hour: int, minute: int, second: int) -> Dt:
    if month < 1 or month > 12:
        raise ValueError(f"month must be in 1..12, got {month}")
    if day < 1 or day > days_in_month(year, month):
        raise ValueError(f"day is out of range for month, got {day}")
    if hour < 0 or hour > 23:
        raise ValueError(f"hour must be in 0..23, got {hour}")
    if minute < 0 or minute > 59:
        raise ValueError(f"minute must be in 0..59, got {minute}")
    if second < 0 or second > 59:
        raise ValueError(f"second must be in 0..59, got {second}")
    return Dt(year, month, day, hour, minute, second)


def make_date(year: int, month: int, day: int) -> Dt:
    return make(year, month, day, 0, 0, 0)


def days_from_civil(year: int, month: int, day: int) -> int:
    y: int = year
    if month <= 2:
        y -= 1
    era: int = y // 400
    yoe: int = y - era * 400
    mp: int = (month + 9) % 12
    doy: int = (153 * mp + 2) // 5 + day - 1
    doe: int = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - DAYS_TO_UNIX


def civil_from_days(z: int) -> Dt:
    zz: int = z + DAYS_TO_UNIX
    era: int = zz // 146097
    doe: int = zz - era * 146097
    yoe: int = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y: int = yoe + era * 400
    doy: int = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp: int = (5 * doy + 2) // 153
    d: int = doy - (153 * mp + 2) // 5 + 1
    m: int = mp + 3 if mp < 10 else mp - 9
    if m <= 2:
        y += 1
    return Dt(y, m, d, 0, 0, 0)


def to_unix(dt: Ref[Dt]) -> int:
    days: int = days_from_civil(dt.year, dt.month, dt.day)
    return days * SECS_PER_DAY + dt.hour * 3600 + dt.minute * 60 + dt.second


def from_unix(ts: int) -> Dt:
    days: int = ts // SECS_PER_DAY
    rem: int = ts % SECS_PER_DAY
    d: Dt = civil_from_days(days)
    return Dt(d.year, d.month, d.day, rem // 3600, (rem // 60) % 60, rem % 60)


def now_utc() -> Dt:
    return from_unix(int(time()))


def weekday(dt: Ref[Dt]) -> int:
    days: int = days_from_civil(dt.year, dt.month, dt.day)
    return (days + 3) % 7


def day_of_year(dt: Ref[Dt]) -> int:
    return days_from_civil(dt.year, dt.month, dt.day) \
        - days_from_civil(dt.year, 1, 1) + 1


def add_days(dt: Ref[Dt], n: int) -> Dt:
    return from_unix(to_unix(dt) + n * SECS_PER_DAY)


def add_seconds(dt: Ref[Dt], n: int) -> Dt:
    return from_unix(to_unix(dt) + n)


def diff_seconds(a: Ref[Dt], b: Ref[Dt]) -> int:
    return to_unix(a) - to_unix(b)


def _pad(n: int, width: int) -> str:
    out: str = str(n)
    while len(out) < width:
        out = "0" + out
    return out


def iso_format(dt: Ref[Dt]) -> str:
    date: str = f"{_pad(dt.year, 4)}-{_pad(dt.month, 2)}-{_pad(dt.day, 2)}"
    return f"{date}T{_pad(dt.hour, 2)}:{_pad(dt.minute, 2)}:{_pad(dt.second, 2)}"


def _int_field(s: str, what: str) -> int:
    if len(s) == 0:
        raise ValueError(f"invalid ISO {what}: {s!r}")
    for c in s:
        if c < "0" or c > "9":
            raise ValueError(f"invalid ISO {what}: {s!r}")
    return int(s)


def parse_iso(s: str) -> Dt:
    body: str = s.strip()
    date_part: str = body
    time_part: str = ""
    for i in range(len(body)):
        c: str = body[i]
        if c == "T" or c == " ":
            date_part = body[:i]
            time_part = body[i + 1:]
            break
    dsegs: list[str] = date_part.split("-")
    if len(dsegs) != 3:
        raise ValueError(f"invalid ISO date: {s!r}")
    year: int = _int_field(dsegs[0], "year")
    month: int = _int_field(dsegs[1], "month")
    day: int = _int_field(dsegs[2], "day")
    hour: int = 0
    minute: int = 0
    second: int = 0
    if time_part != "":
        tsegs: list[str] = time_part.split(":")
        if len(tsegs) != 3:
            raise ValueError(f"invalid ISO time: {s!r}")
        hour = _int_field(tsegs[0], "hour")
        minute = _int_field(tsegs[1], "minute")
        second = _int_field(tsegs[2], "second")
    return make(year, month, day, hour, minute, second)


def _digits(s: str) -> bool:
    """True when a string is non-empty and all ASCII digits."""
    if len(s) == 0:
        return False
    for c in s:
        if c < "0" or c > "9":
            return False
    return True


def _parse_offset(text: str, s: str) -> int:
    """Microseconds of an ISO offset body (`HH`, `HHMM`, `HH:MM`, `HH:MM:SS[.ffffff]`)."""
    frac: str = ""
    body: str = text
    at: int = body.find(".")
    if at >= 0:
        frac = body[at + 1:]
        body = body[:at]
    hh: str = ""
    mm: str = "00"
    ss: str = "00"
    if body.find(":") >= 0:
        segs: list[str] = body.split(":")
        if len(segs) < 2 or len(segs) > 3:
            raise ValueError(f"Invalid isoformat string: {s!r}")
        hh = segs[0]
        mm = segs[1]
        if len(segs) == 3:
            ss = segs[2]
    elif len(body) == 4:
        hh = body[:2]
        mm = body[2:]
    else:
        hh = body
    if len(hh) != 2 or len(mm) != 2 or len(ss) != 2 or not _digits(hh) \
            or not _digits(mm) or not _digits(ss):
        raise ValueError(f"Invalid isoformat string: {s!r}")
    us: int = 0
    if len(frac) > 0:
        if not _digits(frac) or len(frac) > 6:
            raise ValueError(f"Invalid isoformat string: {s!r}")
        padded: str = frac
        while len(padded) < 6:
            padded = padded + "0"
        us = int(padded)
    return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000000 + us


def _parse_iso_parts(s: str) -> list[int]:
    """[year, month, day, hour, minute, second, microsecond, has_tz, offset_us] from ISO 8601 text."""
    body: str = s
    has_tz: int = 0
    off_us: int = 0
    date_part: str = body
    time_part: str = ""
    if len(body) > 10:
        date_part = body[:10]
        time_part = body[11:]
    nt: int = len(time_part)
    if nt > 0 and (time_part.endswith("Z") or time_part.endswith("z")):
        time_part = time_part[:nt - 1]
        has_tz = 1
    else:
        sign_at: int = time_part.find("+")
        sign: int = 1
        if sign_at < 0:
            sign_at = time_part.find("-")
            sign = -1
        if sign_at >= 0:
            off_us = sign * _parse_offset(time_part[sign_at + 1:], s)
            if off_us <= -86400000000 or off_us >= 86400000000:
                raise ValueError(f"Invalid isoformat string: {s!r}")
            time_part = time_part[:sign_at]
            has_tz = 1
    dsegs: list[str] = date_part.split("-")
    if len(dsegs) != 3 or len(dsegs[0]) != 4 or not _digits(dsegs[0]) \
            or not _digits(dsegs[1]) or not _digits(dsegs[2]):
        raise ValueError(f"Invalid isoformat string: {s!r}")
    hh: int = 0
    mi: int = 0
    ss: int = 0
    us: int = 0
    if len(time_part) > 0:
        if time_part.find("+") >= 0 or time_part.find("-") >= 0:
            raise ValueError(f"Invalid isoformat string: {s!r}")
        rest: str = time_part
        frac: str = ""
        at: int = rest.find(".")
        if at >= 0:
            frac = rest[at + 1:]
            rest = rest[:at]
        tsegs: list[str] = rest.split(":")
        if len(tsegs) < 2 or len(tsegs) > 3 or not _digits(tsegs[0]) \
                or not _digits(tsegs[1]):
            raise ValueError(f"Invalid isoformat string: {s!r}")
        hh = int(tsegs[0])
        mi = int(tsegs[1])
        if len(tsegs) == 3:
            if not _digits(tsegs[2]):
                raise ValueError(f"Invalid isoformat string: {s!r}")
            ss = int(tsegs[2])
        if len(frac) > 0:
            if not _digits(frac) or len(frac) > 6:
                raise ValueError(f"Invalid isoformat string: {s!r}")
            padded: str = frac
            while len(padded) < 6:
                padded = padded + "0"
            us = int(padded)
    return [int(dsegs[0]), int(dsegs[1]), int(dsegs[2]), hh, mi, ss, us, has_tz, off_us]


MINYEAR: int = 1
MAXYEAR: int = 9999
_EPOCH_ORDINAL: int = 719163


@dataclass
class timedelta:
    days: int = 0
    seconds: int = 0
    microseconds: int = 0
    milliseconds: int = 0
    minutes: int = 0
    hours: int = 0
    weeks: int = 0

    def __post_init__(self: Mut[timedelta]) -> None:
        total: int = ((self.weeks * 7 + self.days) * 86400 + self.hours * 3600
                      + self.minutes * 60 + self.seconds) * 1000000 \
            + self.milliseconds * 1000 + self.microseconds
        self.days = total // 86400000000
        rem: int = total % 86400000000
        self.seconds = rem // 1000000
        self.microseconds = rem % 1000000
        self.milliseconds = 0
        self.minutes = 0
        self.hours = 0
        self.weeks = 0

    def total_seconds(self: Ref[timedelta]) -> float:
        return ((self.days * 86400 + self.seconds) * 1000000
                + self.microseconds) / 1000000.0

    def __repr__(self: Ref[timedelta]) -> str:
        args: list[str] = []
        if self.days != 0:
            args.append(f"days={self.days}")
        if self.seconds != 0:
            args.append(f"seconds={self.seconds}")
        if self.microseconds != 0:
            args.append(f"microseconds={self.microseconds}")
        if len(args) == 0:
            return "datetime.timedelta(0)"
        return "datetime.timedelta(" + ", ".join(args) + ")"

    def __str__(self: Ref[timedelta]) -> str:
        mm: int = self.seconds // 60
        ss: int = self.seconds % 60
        hh: int = mm // 60
        mm = mm % 60
        s: str = f"{hh}:{_pad(mm, 2)}:{_pad(ss, 2)}"
        if self.days != 0:
            plural: str = "" if self.days == 1 or self.days == -1 else "s"
            s = f"{self.days} day{plural}, " + s
        if self.microseconds != 0:
            s = s + "." + _pad(self.microseconds, 6)
        return s

    def _total_us(self: Ref[timedelta]) -> int:
        return (self.days * 86400 + self.seconds) * 1000000 + self.microseconds

    def __add__(self: Ref[timedelta], other: Ref[timedelta]) -> timedelta:
        return _td_from_us(self._total_us() + other._total_us())

    def __sub__(self: Ref[timedelta], other: Ref[timedelta]) -> timedelta:
        return _td_from_us(self._total_us() - other._total_us())

    def __neg__(self: Ref[timedelta]) -> timedelta:
        return _td_from_us(-self._total_us())

    def __mul__(self: Ref[timedelta], n: int) -> timedelta:
        return _td_from_us(self._total_us() * n)

    def __lt__(self: Ref[timedelta], other: Ref[timedelta]) -> bool:
        return self._total_us() < other._total_us()

    def __le__(self: Ref[timedelta], other: Ref[timedelta]) -> bool:
        return self._total_us() <= other._total_us()

    def __gt__(self: Ref[timedelta], other: Ref[timedelta]) -> bool:
        return self._total_us() > other._total_us()

    def __ge__(self: Ref[timedelta], other: Ref[timedelta]) -> bool:
        return self._total_us() >= other._total_us()


def _td_from_us(us: int) -> timedelta:
    """Build a normalized timedelta from a microsecond count."""
    d: int = us // 86400000000
    rem: int = us % 86400000000
    return timedelta(d, rem // 1000000, rem % 1000000)


def _fmt_offset(us: int, sep: str) -> str:
    """Render a UTC offset as ±HH<sep>MM[<sep>SS[.ffffff]] (CPython's tzname/isoformat style)."""
    sign: str = "+"
    v: int = us
    if v < 0:
        sign = "-"
        v = -v
    micro: int = v % 1000000
    secs: int = v // 1000000
    s: str = sign + _pad(secs // 3600, 2) + sep + _pad((secs // 60) % 60, 2)
    if secs % 60 != 0 or micro != 0:
        s = s + sep + _pad(secs % 60, 2)
    if micro != 0:
        s = s + "." + _pad(micro, 6)
    return s


@dataclass
class timezone:
    offset: timedelta
    name: str | None = None

    def __post_init__(self: Mut[timezone]) -> None:
        us: int = self.offset._total_us()
        if us <= -86400000000 or us >= 86400000000:
            raise ValueError("offset must be a timedelta strictly between "
                             "-timedelta(hours=24) and timedelta(hours=24), "
                             f"not {self.offset!r}.")

    def utcoffset(self: Ref[timezone], dt: None = None) -> timedelta:
        return _td_from_us(self.offset._total_us())

    def dst(self: Ref[timezone], dt: None = None) -> None:
        return None

    def tzname(self: Ref[timezone], dt: None = None) -> str:
        if self.name is not None:
            return self.name
        us: int = self.offset._total_us()
        if us == 0:
            return "UTC"
        return "UTC" + _fmt_offset(us, ":")

    def __str__(self: Ref[timezone]) -> str:
        return self.tzname()

    def __repr__(self: Ref[timezone]) -> str:
        if self.name is None:
            if self.offset._total_us() == 0:
                return "datetime.timezone.utc"
            return f"datetime.timezone({self.offset!r})"
        return f"datetime.timezone({self.offset!r}, {self.name!r})"

    def __eq__(self: Ref[timezone], other: Ref[timezone]) -> bool:
        return self.offset._total_us() == other.offset._total_us()


timezone.utc = timezone(timedelta(0))
UTC = timezone(timedelta(0))


def _tz_clone(t: Ref[timezone]) -> timezone:
    """An equal, independently owned copy of a timezone."""
    return timezone(_td_from_us(t.offset._total_us()), t.name)


def _check_date_fields(year: int, month: int, day: int) -> None:
    """Validate date fields with CPython 3.11's messages."""
    if year < MINYEAR or year > MAXYEAR:
        raise ValueError(f"year {year} is out of range")
    if month < 1 or month > 12:
        raise ValueError("month must be in 1..12")
    if day < 1 or day > days_in_month(year, month):
        raise ValueError("day is out of range for month")


@dataclass
class date:
    year: int
    month: int
    day: int

    def __post_init__(self: Mut[date]) -> None:
        _check_date_fields(self.year, self.month, self.day)

    def __repr__(self: Ref[date]) -> str:
        return f"datetime.date({self.year}, {self.month}, {self.day})"

    @staticmethod
    def fromisoformat(text: str) -> date:
        """Parse an ISO 8601 date (`YYYY-MM-DD`)."""
        if len(text) != 10:
            raise ValueError(f"Invalid isoformat string: {text!r}")
        p: list[int] = _parse_iso_parts(text)
        return date(p[0], p[1], p[2])

    def isoformat(self: Ref[date]) -> str:
        return f"{_pad(self.year, 4)}-{_pad(self.month, 2)}-{_pad(self.day, 2)}"

    def __str__(self: Ref[date]) -> str:
        return self.isoformat()

    def toordinal(self: Ref[date]) -> int:
        return days_from_civil(self.year, self.month, self.day) + _EPOCH_ORDINAL

    def weekday(self: Ref[date]) -> int:
        return (self.toordinal() + 6) % 7

    def isoweekday(self: Ref[date]) -> int:
        return self.weekday() + 1

    def replace(self: Ref[date], year: int = -1, month: int = -1,
                day: int = -1) -> date:
        y: int = self.year if year < 0 else year
        m: int = self.month if month < 0 else month
        d: int = self.day if day < 0 else day
        return date(y, m, d)

    def __sub__(self: Ref[date], other: Ref[date]) -> timedelta:
        return _td_from_us((self.toordinal() - other.toordinal()) * 86400000000)

    def __add__(self: Ref[date], other: Ref[timedelta]) -> date:
        moved: Dt = civil_from_days(
            days_from_civil(self.year, self.month, self.day) + other.days)
        return date(moved.year, moved.month, moved.day)

    def __lt__(self: Ref[date], other: Ref[date]) -> bool:
        return self.toordinal() < other.toordinal()

    def __le__(self: Ref[date], other: Ref[date]) -> bool:
        return self.toordinal() <= other.toordinal()

    def __gt__(self: Ref[date], other: Ref[date]) -> bool:
        return self.toordinal() > other.toordinal()

    def __ge__(self: Ref[date], other: Ref[date]) -> bool:
        return self.toordinal() >= other.toordinal()


@dataclass
class datetime:
    year: int
    month: int
    day: int
    hour: int = 0
    minute: int = 0
    second: int = 0
    microsecond: int = 0
    tzinfo: timezone | None = None

    def __post_init__(self: Mut[datetime]) -> None:
        _check_date_fields(self.year, self.month, self.day)
        if self.hour < 0 or self.hour > 23:
            raise ValueError("hour must be in 0..23")
        if self.minute < 0 or self.minute > 59:
            raise ValueError("minute must be in 0..59")
        if self.second < 0 or self.second > 59:
            raise ValueError("second must be in 0..59")
        if self.microsecond < 0 or self.microsecond > 999999:
            raise ValueError("microsecond must be in 0..999999")

    def __repr__(self: Ref[datetime]) -> str:
        s: str = (f"datetime.datetime({self.year}, {self.month}, {self.day}, "
                  f"{self.hour}, {self.minute}")
        if self.second != 0 or self.microsecond != 0:
            s = s + f", {self.second}"
        if self.microsecond != 0:
            s = s + f", {self.microsecond}"
        if self.tzinfo is not None:
            s = s + f", tzinfo={self.tzinfo!r}"
        return s + ")"

    @staticmethod
    def utcnow() -> datetime:
        return _dt_from_us(int(time() * 1000000.0))

    @staticmethod
    def now(tz: Owned[timezone | None] = None) -> datetime:
        """The current time; aware in `tz` when given, else naive UTC (stdlib: local time)."""
        return _from_utc_us(int(time() * 1000000.0), move(tz))

    @staticmethod
    def fromisoformat(text: str) -> datetime:
        """Parse ISO 8601 text (`YYYY-MM-DD[THH:MM[:SS[.ffffff]]][Z|±HH:MM[:SS]]`)."""
        p: list[int] = _parse_iso_parts(text)
        if p[7] == 0:
            return datetime(p[0], p[1], p[2], p[3], p[4], p[5], p[6])
        return datetime(p[0], p[1], p[2], p[3], p[4], p[5], p[6],
                        tzinfo=timezone(_td_from_us(p[8])))

    @staticmethod
    def fromtimestamp(ts: float, tz: Owned[timezone | None] = None) -> datetime:
        """The datetime for a Unix timestamp: aware in `tz` when given, else naive UTC (stdlib: local)."""
        return _from_utc_us(int(ts * 1000000.0), move(tz))

    def date(self: Ref[datetime]) -> date:
        return date(self.year, self.month, self.day)

    def utcoffset(self: Ref[datetime]) -> timedelta | None:
        if self.tzinfo is None:
            return None
        return self.tzinfo.utcoffset()

    def tzname(self: Ref[datetime]) -> str | None:
        if self.tzinfo is None:
            return None
        return self.tzinfo.tzname()

    def _tz(self: Ref[datetime]) -> timezone | None:
        if self.tzinfo is None:
            return None
        return _tz_clone(self.tzinfo)

    def _off_us(self: Ref[datetime]) -> int:
        if self.tzinfo is None:
            return 0
        return self.tzinfo.offset._total_us()

    def isoformat(self: Ref[datetime], sep: str = "T") -> str:
        d: str = f"{_pad(self.year, 4)}-{_pad(self.month, 2)}-{_pad(self.day, 2)}"
        t: str = f"{_pad(self.hour, 2)}:{_pad(self.minute, 2)}:{_pad(self.second, 2)}"
        if self.microsecond != 0:
            t = t + "." + _pad(self.microsecond, 6)
        if self.tzinfo is not None:
            t = t + _fmt_offset(self._off_us(), ":")
        return d + sep + t

    def __str__(self: Ref[datetime]) -> str:
        return self.isoformat(" ")

    def toordinal(self: Ref[datetime]) -> int:
        return days_from_civil(self.year, self.month, self.day) + _EPOCH_ORDINAL

    def weekday(self: Ref[datetime]) -> int:
        return (self.toordinal() + 6) % 7

    def isoweekday(self: Ref[datetime]) -> int:
        return self.weekday() + 1

    def _total_us(self: Ref[datetime]) -> int:
        days: int = days_from_civil(self.year, self.month, self.day)
        return ((days * 86400 + self.hour * 3600 + self.minute * 60
                 + self.second) * 1000000 + self.microsecond)

    def _utc_us(self: Ref[datetime]) -> int:
        return self._total_us() - self._off_us()

    def timestamp(self: Ref[datetime]) -> float:
        """Seconds since the epoch; naive values are taken as UTC (stdlib: local time)."""
        return self._utc_us() / 1000000.0

    def astimezone(self: Ref[datetime], tz: Ref[timezone]) -> datetime:
        """The same instant expressed in `tz` (naive values are taken as UTC)."""
        return _from_utc_us(self._utc_us(), _tz_clone(tz))

    def replace(self: Ref[datetime], year: int = -1, month: int = -1, day: int = -1,
                hour: int = -1, minute: int = -1, second: int = -1,
                microsecond: int = -1) -> datetime:
        return datetime(self.year if year < 0 else year,
                        self.month if month < 0 else month,
                        self.day if day < 0 else day,
                        self.hour if hour < 0 else hour,
                        self.minute if minute < 0 else minute,
                        self.second if second < 0 else second,
                        self.microsecond if microsecond < 0 else microsecond,
                        self._tz())

    def _cmp_key(self: Ref[datetime], other: Ref[datetime]) -> int:
        if (self.tzinfo is None) != (other.tzinfo is None):
            raise TypeError("can't compare offset-naive and offset-aware datetimes")
        return self._utc_us() - other._utc_us()

    def __sub__(self: Ref[datetime], other: Ref[datetime]) -> timedelta:
        if (self.tzinfo is None) != (other.tzinfo is None):
            raise TypeError("can't subtract offset-naive and offset-aware datetimes")
        return _td_from_us(self._utc_us() - other._utc_us())

    def __add__(self: Ref[datetime], other: Ref[timedelta]) -> datetime:
        moved: datetime = _dt_from_us(self._total_us() + other._total_us())
        moved.tzinfo = self._tz()
        return moved

    def __eq__(self: Ref[datetime], other: Ref[datetime]) -> bool:
        if (self.tzinfo is None) != (other.tzinfo is None):
            return False
        return self._utc_us() == other._utc_us()

    def __lt__(self: Ref[datetime], other: Ref[datetime]) -> bool:
        return self._cmp_key(other) < 0

    def __le__(self: Ref[datetime], other: Ref[datetime]) -> bool:
        return self._cmp_key(other) <= 0

    def __gt__(self: Ref[datetime], other: Ref[datetime]) -> bool:
        return self._cmp_key(other) > 0

    def __ge__(self: Ref[datetime], other: Ref[datetime]) -> bool:
        return self._cmp_key(other) >= 0


def _from_utc_us(us: int, tz: Owned[timezone | None]) -> datetime:
    """The datetime for a UTC microsecond instant, shifted into `tz` when one is given."""
    if tz is None:
        return _dt_from_us(us)
    local: datetime = _dt_from_us(us + tz.offset._total_us())
    local.tzinfo = move(tz)
    return local


def _dt_from_us(us: int) -> datetime:
    """Build a datetime from microseconds since the Unix epoch."""
    days: int = us // 86400000000
    rem: int = us % 86400000000
    d: Dt = civil_from_days(days)
    secs: int = rem // 1000000
    return datetime(d.year, d.month, d.day, secs // 3600, (secs // 60) % 60,
                    secs % 60, rem % 1000000)


def utcnow() -> datetime:
    """Return the current UTC datetime (stands in for datetime.utcnow())."""
    return _dt_from_us(int(time() * 1000000.0))
