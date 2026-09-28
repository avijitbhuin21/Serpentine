"""serp-molt: date / datetime / timedelta / UUID fields parsed from strings."""
from __future__ import annotations

from serp_datetime import date, datetime, timedelta
from serp_molt import BaseModel, ValidationError
from serp_uuid import UUID
from serpentine import PyVal


class Ev(BaseModel):
    ident: UUID
    day: date
    at: datetime
    span: timedelta


class Maybe(BaseModel):
    when: date | None = None


def show_errors(ident: PyVal, day: PyVal, at: PyVal, span: PyVal) -> None:
    """Print every validation error of one candidate Ev mapping."""
    obj: dict[str, PyVal] = {"ident": ident, "day": day, "at": at, "span": span}
    for er in Ev.model_validate_errors(obj):
        print(er["type"], er["loc"], er["msg"])


def main() -> None:
    ev = Ev.model_validate({"ident": "0B4A5E1C-8E4D-4F3A-9C2B-1D6E7F80A912",
                            "day": "2026-07-27",
                            "at": "2026-07-27T13:45:06.000500",
                            "span": 5400.5})
    print(ev.ident, ev.day, ev.at)
    print(ev.day.year, ev.day.month, ev.day.day)
    print(ev.at.hour, ev.at.minute, ev.at.second, ev.at.microsecond)
    print(ev.span.days, ev.span.seconds, ev.span.microseconds)
    print(ev.model_dump_json())

    hexed = Ev.model_validate({"ident": "0b4a5e1c8e4d4f3a9c2b1d6e7f80a912",
                               "day": {"year": 2026, "month": 1, "day": 2},
                               "at": "2026-01-02",
                               "span": "90"})
    print(hexed.model_dump_json())
    print(hexed.at.isoformat(), hexed.span.total_seconds())

    empty = Maybe.model_validate({})
    print(empty.model_dump_json())
    given = Maybe.model_validate({"when": "1999-12-31"})
    print(given.model_dump_json(), given.when is not None)

    good = "0b4a5e1c-8e4d-4f3a-9c2b-1d6e7f80a912"
    show_errors("nope", "2026-07-27", "2026-07-27", 1)
    show_errors(good, "2026-13-01", "2026-07-27", 1)
    show_errors(good, "2026-07-27", "yesterday", 1)
    show_errors(good, 20260727, "2026-07-27", 1)
    show_errors(good, "2026-07-27", "2026-07-27", "soon")

    try:
        boom = Ev.model_validate({"ident": "x", "day": "x", "at": "x", "span": "x"})
        print("unreachable", boom.day.year)
    except ValidationError as e:
        print(e)

    print(Ev.model_json_schema())
    print(Maybe.model_json_schema())


if __name__ == "__main__":
    main()
