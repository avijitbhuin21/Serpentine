"""serp-molt — drop-in `pydantic` v2 models in the Serpentine subset.

`from serp_molt import BaseModel, Field, ValidationError` gives the pydantic v2
surface: annotated model classes, keyword construction, `model_validate`,
`model_validate_json`, `model_dump`, `model_dump_json`, `model_json_schema`,
`Field()` constraints (including `Annotated[T, Field(...)]`), nested models,
`@field_validator`/`@model_validator`, `Annotated[T, AfterValidator(f)]`,
`model_config = ConfigDict(...)` (including `frozen`, `validate_assignment` and
`alias_generator`), `Model(**data)`, and accumulated `ValidationError`s. The
same source compiles natively with `serp` and imports under CPython.

Divergences (see README): validation errors are read with
`model_validate_errors()` instead of `e.errors()`, `loc` is a list rather than a
tuple, `model_construct`/`model_copy` take a dict rather than `**kwargs`,
validators take one `PyVal` with no `ValidationInfo`, and ints are int64.
"""
from __future__ import annotations

from serpentine import (AfterValidator, Base64, BeforeValidator, ConfigDict, Field, Json, Mut,
                        PyVal, Ref, SkipValidation, computed_field, conbytes, confloat, conint,
                        conlist, constr, dataclass, field_serializer,
                        field_validator, fields_build, fields_json, fields_of, fields_set,
                        hooks_json, model_serializer, model_validator, pyval_kind, run_hook,
                        run_hook_get, run_hook_info, run_hook_self, run_hook_val)
from serp_json import loads
from serp_base64 import b64decode, b64encode
from serp_re import Match, search
from serp_datetime import date, datetime
from serp_uuid import UUID
from typing import Annotated, Self

HEX: str = "0123456789abcdef"
INT_MAX_TEXT: int = 18

PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NegativeInt = Annotated[int, Field(lt=0)]
NonPositiveInt = Annotated[int, Field(le=0)]
PositiveFloat = Annotated[float, Field(gt=0.0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
NegativeFloat = Annotated[float, Field(lt=0.0)]
NonPositiveFloat = Annotated[float, Field(le=0.0)]
StrictInt = Annotated[int, Field(strict=True)]
StrictFloat = Annotated[float, Field(strict=True)]
StrictBool = Annotated[bool, Field(strict=True)]
StrictStr = Annotated[str, Field(strict=True)]
StrictBytes = Annotated[bytes, Field(strict=True)]
Base64Bytes = Annotated[bytes, Base64()]
AnyUrl = Annotated[str, Field(pattern="^[a-zA-Z][a-zA-Z0-9+.\\-]*://[^\\s/?#]+[^\\s]*$")]
AnyHttpUrl = Annotated[str, Field(pattern="^https?://[^\\s/?#]+[^\\s]*$")]
HttpUrl = Annotated[str, Field(pattern="^https?://[^\\s/?#]+[^\\s]*$")]
EmailStr = Annotated[str, Field(pattern="^[^@\\s]+@[^@\\s]+\\.[a-zA-Z]{2,}$")]


def _is_true_word(s: str) -> bool:
    """The strings pydantic accepts as boolean true."""
    return s == "1" or s == "on" or s == "t" or s == "true" or s == "y" or s == "yes"


def _is_false_word(s: str) -> bool:
    """The strings pydantic accepts as boolean false."""
    return s == "0" or s == "off" or s == "f" or s == "false" or s == "n" or s == "no"


class ValidationError(ValueError):
    """Raised when input does not validate against a model; message is pydantic-shaped."""


class PydanticCustomError(ValueError):
    """Raised inside a validator to pick the error `type`: `PydanticCustomError("kind: msg")`."""


def _has(d: PyVal, key: str) -> bool:
    """True when a PyVal mapping carries `key`."""
    if pyval_kind(d) != "dict":
        return False
    for k in d:
        if str(k) == key:
            return True
    return False


def _get(d: PyVal, key: str) -> PyVal:
    """The value at `key`, or None when absent."""
    if _has(d, key):
        return d[key]
    return None


def _loc(parent: PyVal, part: PyVal) -> PyVal:
    """Extend an error location path with one more component."""
    out: list[PyVal] = []
    if pyval_kind(parent) == "list":
        for p in parent:
            out.append(p)
    out.append(part)
    return out


def _err(kind: str, loc: PyVal, msg: str, given: PyVal) -> PyVal:
    """One pydantic-shaped error entry."""
    e: dict[str, PyVal] = {"type": kind, "loc": loc, "msg": msg, "input": given}
    return e


def _numtext(v: PyVal) -> str:
    """Render a numeric constraint bound the way pydantic prints it."""
    if pyval_kind(v) == "float":
        f: float = float(v)
        return f"{f}"
    return str(v)


def _plural(n: int, noun: str) -> str:
    """`1 item` / `2 items`."""
    if n == 1:
        return f"1 {noun}"
    return f"{n} {noun}s"


def _is_digits(s: str) -> bool:
    """True for a non-empty run of ASCII digits."""
    if len(s) == 0:
        return False
    for c in s:
        if c < "0" or c > "9":
            return False
    return True


def _unsigned(s: str) -> str:
    """Drop a leading sign."""
    if s.startswith("+") or s.startswith("-"):
        return s[1:]
    return s


def _is_int_text(s: str) -> bool:
    """True for a decimal integer literal that fits Serpentine's int64 parser."""
    body: str = _unsigned(s)
    if len(body) > INT_MAX_TEXT:
        return False
    return _is_digits(body)


def _is_float_text(s: str) -> bool:
    """True for a decimal float literal (no inf/nan words)."""
    body: str = _unsigned(s)
    digits: int = 0
    dots: int = 0
    i: int = 0
    while i < len(body):
        c: str = body[i]
        if c >= "0" and c <= "9":
            digits += 1
        elif c == ".":
            dots += 1
            if dots > 1:
                return False
        elif c == "e" or c == "E":
            if digits == 0:
                return False
            return _is_digits(_unsigned(body[i + 1:]))
        else:
            return False
        i += 1
    return digits > 0


def _co_int(v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """Lax coercion to int: int, integral float, or a decimal string."""
    k: str = pyval_kind(v)
    if k == "int":
        return v
    if k == "float":
        f: float = float(v)
        if f > 9.0e18 or f < -9.0e18 or f != f:
            errs.append(_err("int_from_float", loc,
                             "Input should be a valid integer, got a number outside the "
                             "int64 range", v))
            return None
        i: int = int(f)
        if float(i) != f:
            errs.append(_err("int_from_float", loc,
                             "Input should be a valid integer, got a number with a "
                             "fractional part", v))
            return None
        return i
    if k == "str":
        s: str = str(v).strip()
        if not _is_int_text(s):
            errs.append(_err("int_parsing", loc,
                             "Input should be a valid integer, unable to parse string as "
                             "an integer", v))
            return None
        return int(s)
    errs.append(_err("int_type", loc, "Input should be a valid integer", v))
    return None


def _co_float(v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """Lax coercion to float: float, int, or a decimal string."""
    k: str = pyval_kind(v)
    if k == "float":
        return v
    if k == "int":
        return float(int(v))
    if k == "str":
        s: str = str(v).strip()
        if not _is_float_text(s):
            errs.append(_err("float_parsing", loc,
                             "Input should be a valid number, unable to parse string as a "
                             "number", v))
            return None
        return float(s)
    errs.append(_err("float_type", loc, "Input should be a valid number", v))
    return None


def _co_bool(v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """Lax coercion to bool: bool, 0/1, or a truthy/falsy word."""
    k: str = pyval_kind(v)
    if k == "bool":
        return v
    if k == "int" or k == "float":
        f: float = float(v)
        if f == 0.0:
            return False
        if f == 1.0:
            return True
        errs.append(_err("bool_parsing", loc,
                         "Input should be a valid boolean, unable to interpret input", v))
        return None
    if k == "str":
        s: str = str(v).strip().lower()
        if _is_true_word(s):
            return True
        if _is_false_word(s):
            return False
        errs.append(_err("bool_parsing", loc,
                         "Input should be a valid boolean, unable to interpret input", v))
        return None
    errs.append(_err("bool_type", loc, "Input should be a valid boolean", v))
    return None


def _num_meta(meta: PyVal, v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> None:
    """Numeric Field() constraints: gt/ge/lt/le/multiple_of."""
    x: float = float(v)
    if _has(meta, "gt") and not x > float(meta["gt"]):
        errs.append(_err("greater_than", loc,
                         "Input should be greater than " + _numtext(meta["gt"]), v))
    if _has(meta, "ge") and not x >= float(meta["ge"]):
        errs.append(_err("greater_than_equal", loc,
                         "Input should be greater than or equal to "
                         + _numtext(meta["ge"]), v))
    if _has(meta, "lt") and not x < float(meta["lt"]):
        errs.append(_err("less_than", loc,
                         "Input should be less than " + _numtext(meta["lt"]), v))
    if _has(meta, "le") and not x <= float(meta["le"]):
        errs.append(_err("less_than_equal", loc,
                         "Input should be less than or equal to "
                         + _numtext(meta["le"]), v))
    if _has(meta, "multiple_of"):
        step: float = float(meta["multiple_of"])
        if step != 0.0:
            q: float = x / step
            if q > 9.0e18 or q < -9.0e18 or float(int(q)) != q:
                errs.append(_err("multiple_of", loc,
                                 "Input should be a multiple of "
                                 + _numtext(meta["multiple_of"]), v))


def _len_meta(meta: PyVal, n: int, noun: str, unit: str, short: str, long: str,
              suffix: str, v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> None:
    """Shared min_length/max_length enforcement for sized values."""
    if _has(meta, "min_length"):
        low: int = int(meta["min_length"])
        if n < low:
            errs.append(_err(short, loc,
                             f"{noun} should have at least {_plural(low, unit)}{suffix}", v))
    if _has(meta, "max_length"):
        high: int = int(meta["max_length"])
        if n > high:
            errs.append(_err(long, loc,
                             f"{noun} should have at most {_plural(high, unit)}{suffix}", v))


def _str_meta(meta: PyVal, v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> None:
    """String Field() constraints: min_length/max_length/pattern."""
    s: str = str(v)
    _len_meta(meta, len(s), "String", "character", "string_too_short",
              "string_too_long", "", v, loc, errs)
    if _has(meta, "pattern"):
        pat: str = str(meta["pattern"])
        hit: Match | None = search(pat, s)
        if hit is None:
            errs.append(_err("string_pattern_mismatch", loc,
                             f"String should match pattern '{pat}'", v))


def _apply_meta(meta: PyVal, tkind: str, v: PyVal, loc: PyVal,
                errs: Mut[list[PyVal]]) -> None:
    """Enforce every Field() constraint recorded for one field."""
    if pyval_kind(v) == "NoneType":
        return
    if tkind == "int" or tkind == "float":
        _num_meta(meta, v, loc, errs)
    elif tkind == "str":
        _str_meta(meta, v, loc, errs)
    elif tkind == "bytes":
        _len_meta(meta, len(v), "Data", "byte", "bytes_too_short", "bytes_too_long",
                  "", v, loc, errs)
    elif tkind == "list" or tkind == "tuple":
        _len_meta(meta, len(v), "List", "item", "too_short", "too_long",
                  " after validation, not " + str(len(v)), v, loc, errs)
    elif tkind == "dict":
        _len_meta(meta, len(v), "Dictionary", "item", "too_short", "too_long",
                  " after validation, not " + str(len(v)), v, loc, errs)


def _bare_kind(t: PyVal) -> str:
    """The type kind a field's constraints apply to, looking through Optional."""
    k: str = str(t["k"])
    if k == "optional":
        return _bare_kind(t["inner"])
    if k == "set":
        return "list"
    return k


def _spec_kind(t: PyVal) -> str:
    """The runtime PyVal kind a field-type spec accepts."""
    k: str = str(t["k"])
    if k == "none":
        return "NoneType"
    if k == "model" or k == "dict":
        return "dict"
    if k == "tuple" or k == "set":
        return "list"
    if k == "enum":
        return str(t["base"])
    return k


def _default_tag(spec: PyVal, name: str) -> str:
    """The constant default of field `name` in a model spec, as text ("" when absent)."""
    for f in spec["fields"]:
        if str(f["name"]) == name and bool(f["has_default"]) and _has(f, "default"):
            k: str = pyval_kind(f["default"])
            if k == "str" or k == "int":
                return str(f["default"])
    return ""


def _disc_name(t: PyVal) -> str:
    """The discriminator of an all-model union: a shared field with distinct defaults.

    Serpentine has no `Literal`, so the tag is the field's **default** in each member
    (`pet_type: str = "cat"`). Returns "" when the union is not discriminable.
    """
    members: PyVal = t["members"]
    if len(members) < 2:
        return ""
    for m in members:
        if str(m["k"]) != "model":
            return ""
    for f in members[0]["fields"]:
        name: str = str(f["name"])
        seen: list[str] = []
        ok: bool = True
        for m2 in members:
            dv: str = _default_tag(m2, name)
            if dv == "" or _listed(seen, dv):
                ok = False
            else:
                seen.append(dv)
        if ok:
            return name
    return ""


def _disc_pick(t: PyVal, v: PyVal) -> PyVal:
    """The union member whose discriminator default matches the input's tag value."""
    if pyval_kind(v) != "dict":
        return None
    name: str = _disc_name(t)
    if name == "":
        return None
    if not _has(v, name):
        return None
    want: str = str(v[name])
    for m in t["members"]:
        if _default_tag(m, name) == want:
            return m
    return None


def _member_spec(t: PyVal, v: PyVal) -> PyVal:
    """The union member a value selects: by discriminator tag first, then by runtime kind."""
    d: PyVal = _disc_pick(t, v)
    if pyval_kind(d) == "dict":
        return d
    members: PyVal = t["members"]
    got: str = pyval_kind(v)
    for m in members:
        if _spec_kind(m) == got:
            return m
    if got == "int":
        for m2 in members:
            if str(m2["k"]) == "float":
                return m2
    return None


def _member_names(t: PyVal) -> str:
    """The member kinds of a union, as pydantic-style alternatives text."""
    names: list[str] = []
    for m in t["members"]:
        names.append(_spec_kind(m))
    return " or ".join(names)


def _member_tag(m: PyVal) -> str:
    """The union-member label a per-member error is reported under."""
    k: str = str(m["k"])
    if k == "model":
        return str(m["class"])
    if k == "enum":
        return str(m["class"])
    return k


def _quoted_values(t: PyVal) -> str:
    """An enum's allowed values, rendered the way pydantic lists them."""
    vals: list[str] = []
    for x in t["values"]:
        if pyval_kind(x) == "str":
            vals.append(f"'{x}'")
        else:
            vals.append(str(x))
    if len(vals) < 2:
        return " or ".join(vals)
    head: list[str] = []
    i: int = 0
    while i < len(vals) - 1:
        head.append(vals[i])
        i += 1
    return ", ".join(head) + " or " + vals[len(vals) - 1]


def _strict_kind(t: PyVal) -> str:
    """The one runtime kind a `strict=True` field accepts, looking through Optional."""
    if str(t["k"]) == "optional":
        return _strict_kind(t["inner"])
    return _spec_kind(t)


def _strict_bad(meta: PyVal, t: PyVal, v: PyVal, loc: PyVal,
                errs: Mut[list[PyVal]]) -> bool:
    """True when `Field(strict=True)` rejects this input's runtime kind."""
    if not _has(meta, "strict"):
        return False
    if not bool(meta["strict"]):
        return False
    got: str = pyval_kind(v)
    if got == "NoneType":
        return False
    want: str = _strict_kind(t)
    if got == want:
        return False
    if want == "float" and got == "int":
        return False
    code: str = ""
    text: str = ""
    if want == "int":
        code = "int_type"
        text = "Input should be a valid integer"
    elif want == "float":
        code = "float_type"
        text = "Input should be a valid number"
    elif want == "bool":
        code = "bool_type"
        text = "Input should be a valid boolean"
    elif want == "str":
        code = "string_type"
        text = "Input should be a valid string"
    elif want == "bytes":
        code = "bytes_type"
        text = "Input should be a valid bytes"
    if code == "":
        return False
    errs.append(_err(code, loc, text, v))
    return True


def _first_field(t: PyVal) -> str:
    """The name of a model spec's first field, or empty text when it has none."""
    flds: PyVal = t["fields"]
    if len(flds) == 0:
        return ""
    return str(flds[0]["name"])


@dataclass
class SecretStr:
    """pydantic's `SecretStr`: keeps its value out of `str()` and out of every dump."""

    _v: str

    def get_secret_value(self: Ref[SecretStr]) -> str:
        """The wrapped secret, in the clear."""
        return self._v

    def __str__(self: Ref[SecretStr]) -> str:
        return "**********"


def _from_secret(v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """The field mapping of a `SecretStr` built from plain text."""
    if pyval_kind(v) != "str":
        errs.append(_err("string_type", loc, "Input should be a valid string", v))
        return None
    out: dict[str, PyVal] = {"_v": str(v)}
    return out


def _fmt_of(t: PyVal) -> str:
    """The string format a temporal/UUID model field also accepts, else empty text."""
    if str(t["k"]) != "model":
        return ""
    cname: str = str(t["class"])
    n: int = len(t["fields"])
    first: str = _first_field(t)
    if cname == "date" and n == 3 and first == "year":
        return "date"
    if cname == "datetime" and (n == 7 or n == 8) and first == "year":
        return "date-time"
    if cname == "timedelta" and n == 7 and first == "days":
        return "duration"
    if cname == "UUID" and n == 1 and first == "_s":
        return "uuid"
    if cname == "SecretStr" and n == 1 and first == "_v":
        return "secret"
    return ""


def _wrong_temporal(fmt: str, v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> None:
    """Record the type error for a temporal field given something other than text."""
    if fmt == "date":
        errs.append(_err("date_type", loc, "Input should be a valid date", v))
    elif fmt == "date-time":
        errs.append(_err("datetime_type", loc, "Input should be a valid datetime", v))
    else:
        errs.append(_err("uuid_type", loc, "Input should be a valid UUID", v))


def _from_date(v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """The field mapping of a `date` parsed from ISO 8601 text."""
    if pyval_kind(v) != "str":
        _wrong_temporal("date", v, loc, errs)
        return None
    ok: bool = True
    out: dict[str, PyVal] = {}
    try:
        d: date = date.fromisoformat(str(v))
        out = {"year": d.year, "month": d.month, "day": d.day}
    except ValueError:
        ok = False
    if not ok:
        errs.append(_err("date_parsing", loc,
                         "Input should be a valid date in ISO 8601 format", v))
        return None
    return out


def _from_datetime(v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """The field mapping of a `datetime` parsed from ISO 8601 text."""
    if pyval_kind(v) != "str":
        _wrong_temporal("date-time", v, loc, errs)
        return None
    ok: bool = True
    out: dict[str, PyVal] = {}
    try:
        d: datetime = datetime.fromisoformat(str(v))
        out = {"year": d.year, "month": d.month, "day": d.day, "hour": d.hour,
               "minute": d.minute, "second": d.second, "microsecond": d.microsecond,
               "tzinfo": None}
    except ValueError:
        ok = False
    if not ok:
        errs.append(_err("datetime_parsing", loc,
                         "Input should be a valid datetime in ISO 8601 format", v))
        return None
    return out


def _from_uuid(v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """The field mapping of a `UUID` parsed from text."""
    if pyval_kind(v) != "str":
        _wrong_temporal("uuid", v, loc, errs)
        return None
    ok: bool = True
    out: dict[str, PyVal] = {}
    try:
        u: UUID = UUID(str(v))
        out = {"_s": str(u)}
    except ValueError:
        ok = False
    if not ok:
        errs.append(_err("uuid_parsing", loc, "Input should be a valid UUID", v))
        return None
    return out


def _from_duration(v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """The field mapping of a `timedelta` given a number of seconds."""
    got: str = pyval_kind(v)
    secs: float = 0.0
    if got == "int" or got == "float":
        secs = float(v)
    elif got == "str" and _is_float_text(str(v).strip()):
        secs = float(str(v).strip())
    else:
        errs.append(_err("time_delta_parsing", loc,
                         "Input should be a valid timedelta, given as a number of "
                         "seconds", v))
        return None
    total: int = int(secs * 1000000.0)
    days: int = total // 86400000000
    rem: int = total - days * 86400000000
    out: dict[str, PyVal] = {"days": days, "seconds": rem // 1000000,
                             "microseconds": rem % 1000000, "milliseconds": 0,
                             "minutes": 0, "hours": 0, "weeks": 0}
    return out


def _zpad(n: int, width: int) -> str:
    """Zero-padded decimal text of a non-negative number."""
    out: str = str(n)
    while len(out) < width:
        out = "0" + out
    return out


def _duration_secs(d: PyVal) -> PyVal:
    """The total seconds of a dumped `timedelta` mapping."""
    us: int = int(d["days"]) * 86400000000 + int(d["seconds"]) * 1000000 \
        + int(d["microseconds"])
    return float(us) / 1000000.0


def _iso_text(fmt: str, d: PyVal) -> str:
    """ISO 8601 (or canonical UUID) text for a dumped field mapping."""
    if fmt == "uuid":
        return str(d["_s"])
    if fmt == "secret":
        return "**********"
    day: str = f"{_zpad(int(d['year']), 4)}-{_zpad(int(d['month']), 2)}-" \
               f"{_zpad(int(d['day']), 2)}"
    if fmt == "date":
        return day
    clock: str = f"{_zpad(int(d['hour']), 2)}:{_zpad(int(d['minute']), 2)}:" \
                 f"{_zpad(int(d['second']), 2)}"
    us: int = int(d["microsecond"])
    if us != 0:
        clock = clock + "." + _zpad(us, 6)
    return day + "T" + clock


def _val_temporal(fmt: str, v: PyVal, loc: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """Validate a temporal/UUID field from its string (or numeric) spelling."""
    if fmt == "date":
        return _from_date(v, loc, errs)
    if fmt == "date-time":
        return _from_datetime(v, loc, errs)
    if fmt == "duration":
        return _from_duration(v, loc, errs)
    if fmt == "secret":
        return _from_secret(v, loc, errs)
    return _from_uuid(v, loc, errs)


def _val_value(t: PyVal, v: PyVal, loc: PyVal, errs: Mut[list[PyVal]],
               specs: PyVal = None) -> PyVal:
    """Validate and coerce one value against a build-time field type."""
    k: str = str(t["k"])
    got: str = pyval_kind(v)
    if k == "PyVal":
        return v
    if k == "optional":
        if got == "NoneType":
            return None
        return _val_value(t["inner"], v, loc, errs, specs)
    if k == "int":
        return _co_int(v, loc, errs)
    if k == "float":
        return _co_float(v, loc, errs)
    if k == "bool":
        return _co_bool(v, loc, errs)
    if k == "str":
        if got != "str":
            errs.append(_err("string_type", loc, "Input should be a valid string", v))
            return None
        return v
    if k == "bytes":
        if got != "bytes":
            errs.append(_err("bytes_type", loc, "Input should be a valid bytes", v))
            return None
        return v
    if k == "none":
        if got != "NoneType":
            errs.append(_err("none_required", loc, "Input should be None", v))
            return None
        return None
    if k == "list":
        if got != "list":
            errs.append(_err("list_type", loc, "Input should be a valid list", v))
            return None
        items: list[PyVal] = []
        idx: int = 0
        elem: PyVal = t["elem"]
        for x in v:
            items.append(_val_value(elem, x, _loc(loc, idx), errs, specs))
            idx += 1
        return items
    if k == "dict":
        if got != "dict":
            errs.append(_err("dict_type", loc, "Input should be a valid dictionary", v))
            return None
        out: dict[str, PyVal] = {}
        vt: PyVal = t["value"]
        for key in v:
            if pyval_kind(key) != "str":
                errs.append(_err("string_type", _loc(loc, key),
                                 "Input should be a valid string", key))
                continue
            out[str(key)] = _val_value(vt, v[key], _loc(loc, key), errs, specs)
        return out
    if k == "set":
        if got != "list":
            errs.append(_err("set_type", loc, "Input should be a valid set", v))
            return None
        seen: list[PyVal] = []
        sidx: int = 0
        selem: PyVal = t["elem"]
        for y in v:
            item: PyVal = _val_value(selem, y, _loc(loc, sidx), errs, specs)
            if not (item in seen):
                seen.append(item)
            sidx += 1
        return seen
    if k == "enum":
        if got != _spec_kind(t):
            errs.append(_err("enum", loc, "Input should be " + _quoted_values(t), v))
            return None
        if not (v in t["values"]):
            errs.append(_err("enum", loc, "Input should be " + _quoted_values(t), v))
            return None
        return v
    if k == "union":
        member: PyVal = _member_spec(t, v)
        if pyval_kind(member) == "NoneType":
            before: int = len(errs)
            sub: list[PyVal] = []
            for m3 in t["members"]:
                sub = []
                _u: PyVal = _val_value(m3, v, _loc(loc, _member_tag(m3)), sub, specs)
                for e3 in sub:
                    errs.append(e3)
            if len(errs) == before:
                errs.append(_err("union_type", loc,
                                 "Input should be " + _member_names(t), v))
            return None
        return _val_value(member, v, loc, errs, specs)
    if k == "tuple":
        return _val_tuple(t, v, loc, errs, specs)
    if k == "model":
        fmt: str = _fmt_of(t)
        if fmt != "" and got != "dict":
            return _val_temporal(fmt, v, loc, errs)
        return _val_model(_resolved(t, specs), v, loc, errs, specs)
    return v


def _val_tuple(t: PyVal, v: PyVal, loc: PyVal, errs: Mut[list[PyVal]],
               specs: PyVal = None) -> PyVal:
    """Validate a fixed-length tuple field from a list input."""
    if pyval_kind(v) != "list":
        errs.append(_err("tuple_type", loc, "Input should be a valid tuple", v))
        return None
    specs2: PyVal = t["items"]
    want: int = len(specs2)
    if len(v) < want:
        errs.append(_err("too_short", loc,
                         f"Tuple should have at least {_plural(want, 'item')} after "
                         f"validation, not {len(v)}", v))
        return None
    if len(v) > want:
        errs.append(_err("too_long", loc,
                         f"Tuple should have at most {_plural(want, 'item')} after "
                         f"validation, not {len(v)}", v))
        return None
    items: list[PyVal] = []
    i: int = 0
    while i < want:
        items.append(_val_value(specs2[i], v[i], _loc(loc, i), errs, specs))
        i += 1
    return items


def _input_key(f: PyVal) -> str:
    """The input key a field is read from (validation_alias, alias, then its name)."""
    meta: PyVal = _get(f, "meta")
    if _has(meta, "validation_alias"):
        return str(meta["validation_alias"])
    if _has(meta, "alias"):
        return str(meta["alias"])
    return str(f["name"])


def _output_key(f: PyVal) -> str:
    """The key a field is serialized under with by_alias=True."""
    meta: PyVal = _get(f, "meta")
    if _has(meta, "serialization_alias"):
        return str(meta["serialization_alias"])
    if _has(meta, "alias"):
        return str(meta["alias"])
    return str(f["name"])


def _spec_defs(t: PyVal, out: Mut[dict[str, PyVal]]) -> None:
    """Collect every fully expanded model spec in a field-type tree, by class name."""
    k: str = str(t["k"])
    if k == "model" and not _has(t, "cycle"):
        cname: str = str(t["class"])
        if not _has(out, cname):
            out[cname] = t
            for f in t["fields"]:
                _spec_defs(f["type"], out)
    elif k == "optional":
        _spec_defs(t["inner"], out)
    elif k == "list" or k == "set":
        _spec_defs(t["elem"], out)
    elif k == "dict":
        _spec_defs(t["value"], out)
    elif k == "tuple":
        for s in t["items"]:
            _spec_defs(s, out)
    elif k == "union":
        for m in t["members"]:
            _spec_defs(m, out)


def _built_specs(spec: PyVal) -> PyVal:
    """The class-name table used to resolve self-referential model nodes."""
    out: dict[str, PyVal] = {}
    _spec_defs(spec, out)
    return out


def _resolved(t: PyVal, specs: PyVal) -> PyVal:
    """A cycle-stub model node replaced by the full spec it refers back to."""
    if not _has(t, "cycle"):
        return t
    if pyval_kind(specs) != "dict":
        return t
    cname: str = str(t["class"])
    if not _has(specs, cname):
        return t
    return specs[cname]


def _val_model(spec: PyVal, data: PyVal, loc: PyVal, errs: Mut[list[PyVal]],
               specs: PyVal = None) -> PyVal:
    """Validate a mapping against a model's build-time field table."""
    cname: str = str(spec["class"])
    if pyval_kind(data) != "dict":
        errs.append(_err("model_type", loc,
                         f"Input should be a valid dictionary or instance of {cname}",
                         data))
        return None
    sp: PyVal = specs
    if pyval_kind(sp) != "dict":
        sp = _built_specs(spec)
    cfg: PyVal = _config(spec)
    out: dict[str, PyVal] = {}
    known: list[str] = []
    flds: PyVal = spec["fields"]
    for f in flds:
        key: str = _read_key(cfg, f, data)
        name: str = str(f["name"])
        known.append(key)
        if _has(data, key):
            if _has_marker(f, "SkipValidation"):
                out[name] = data[key]
                continue
            fl: PyVal = _loc(loc, key)
            before: int = len(errs)
            t: PyVal = f["type"]
            if _strict_bad(_get(f, "meta"), t, data[key], fl, errs):
                continue
            cv: PyVal = _val_value(t, data[key], fl, errs, sp)
            if len(errs) == before:
                shaped: PyVal = _str_config(cfg, _bare_kind(t), cv, fl, errs)
                _apply_meta(_get(f, "meta"), _bare_kind(t), shaped, fl, errs)
                out[name] = shaped
        elif not bool(f["has_default"]):
            errs.append(_err("missing", _loc(loc, key), "Field required", data))
    if _cfg_str(cfg, "extra", "ignore") == "forbid":
        for k in data:
            if not _listed(known, str(k)):
                errs.append(_err("extra_forbidden", _loc(loc, k),
                                 "Extra inputs are not permitted", data[k]))
    return out


def _listed(names: Ref[list[str]], key: str) -> bool:
    """True when `key` is one of the collected field keys."""
    for n in names:
        if n == key:
            return True
    return False


def _config(spec: PyVal) -> PyVal:
    """A model spec's `model_config` mapping, or an empty one."""
    cfg: PyVal = _get(spec, "config")
    if _has(cfg, "model_config"):
        return cfg["model_config"]
    empty: dict[str, PyVal] = {}
    return empty


def _cfg_str(cfg: PyVal, key: str, fallback: str) -> str:
    """One string `model_config` entry."""
    if _has(cfg, key):
        return str(cfg[key])
    return fallback


def _cfg_bool(cfg: PyVal, key: str) -> bool:
    """One boolean `model_config` entry (absent means false)."""
    if _has(cfg, key):
        return bool(cfg[key])
    return False


def _read_key(cfg: PyVal, f: PyVal, data: PyVal) -> str:
    """The input key a field is read from, honouring `populate_by_name`."""
    key: str = _input_key(f)
    name: str = str(f["name"])
    if key != name and _cfg_bool(cfg, "populate_by_name") and not _has(data, key):
        return name
    return key


def _str_config(cfg: PyVal, tkind: str, v: PyVal, loc: PyVal,
                errs: Mut[list[PyVal]]) -> PyVal:
    """Apply the `str_*` model config entries to one validated string value."""
    if tkind != "str" or pyval_kind(v) != "str":
        return v
    s: str = str(v)
    if _cfg_bool(cfg, "str_strip_whitespace"):
        s = s.strip()
    if _cfg_bool(cfg, "str_to_lower"):
        s = s.lower()
    if _cfg_bool(cfg, "str_to_upper"):
        s = s.upper()
    if _has(cfg, "str_max_length"):
        cap: int = int(cfg["str_max_length"])
        if len(s) > cap:
            errs.append(_err("string_too_long", loc,
                             f"String should have at most {_plural(cap, 'character')}", v))
    if _has(cfg, "str_min_length"):
        low: int = int(cfg["str_min_length"])
        if len(s) < low:
            errs.append(_err("string_too_short", loc,
                             f"String should have at least {_plural(low, 'character')}", v))
    return s


def _replaced(d: PyVal, key: str, v: PyVal) -> PyVal:
    """A copy of a PyVal mapping with one key replaced."""
    out: dict[str, PyVal] = {}
    for k in d:
        out[str(k)] = d[k]
    out[key] = v
    return out


def _cfg_fn(cfg: PyVal, key: str) -> str:
    """The function name of a function-valued model_config entry ('' when absent)."""
    if not _has(cfg, key):
        return ""
    v: PyVal = cfg[key]
    if pyval_kind(v) == "dict" and _has(v, "__fn__"):
        return str(v["__fn__"])
    return ""


def _renamed(d: Ref[dict[str, PyVal]], old: str, new: str) -> dict[str, PyVal]:
    """A copy of a dumped mapping with one key renamed, keeping field order."""
    out: dict[str, PyVal] = {}
    for k, v in d.items():
        if k == old:
            out[new] = v
        else:
            out[k] = v
    return out


def _field_spec(spec: PyVal, name: str) -> PyVal:
    """One field entry of a model spec, by field name."""
    for f in spec["fields"]:
        if str(f["name"]) == name:
            return f
    return None


def _val_field(spec: PyVal, name: str, v: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """Validate one value against a named field's type, str config and Field() constraints."""
    f: PyVal = _field_spec(spec, name)
    if pyval_kind(f) != "dict":
        errs.append(_err("no_such_attribute", [name],
                         f"Object has no attribute '{name}'", v))
        return v
    cfg: PyVal = _config(spec)
    if _has_marker(f, "SkipValidation"):
        return v
    t: PyVal = f["type"]
    fl: list[PyVal] = [name]
    before: int = len(errs)
    cv: PyVal = _val_value(t, v, fl, errs, _built_specs(spec))
    if len(errs) != before:
        return v
    shaped: PyVal = _str_config(cfg, _bare_kind(t), cv, fl, errs)
    _apply_meta(_get(f, "meta"), _bare_kind(t), shaped, fl, errs)
    return shaped


def _marker_fns(f: PyVal, call: str) -> list[str]:
    """Function names referenced by one kind of Annotated marker on a field."""
    out: list[str] = []
    meta: PyVal = _get(f, "meta")
    if not _has(meta, "annotated"):
        return out
    for entry in meta["annotated"]:
        if str(_get(entry, "call")) == call:
            args: PyVal = _get(entry, "args")
            if pyval_kind(args) == "list":
                for a in args:
                    if _has(a, "__fn__"):
                        out.append(str(a["__fn__"]))
    return out


def _has_marker(f: PyVal, call: str) -> bool:
    """True when a field carries a bare `Annotated[...]` marker of the given name."""
    meta: PyVal = _get(f, "meta")
    if not _has(meta, "annotated"):
        return False
    for entry in meta["annotated"]:
        if str(_get(entry, "call")) == call:
            return True
    return False


def _json_markers(spec: PyVal, data: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """Parse every `Annotated[T, Json()]` field out of its JSON text before validation."""
    out: PyVal = data
    if pyval_kind(data) != "dict":
        return out
    for f in spec["fields"]:
        if _has_marker(f, "Json"):
            key: str = _read_key(_config(spec), f, out)
            if _has(out, key):
                cur: PyVal = out[key]
                if pyval_kind(cur) == "str":
                    try:
                        out = _replaced(out, key, loads(str(cur)))
                    except ValueError as exc:
                        errs.append(_err("json_invalid", [key],
                                         f"Invalid JSON: {exc}", cur))
    return out


def _b64_markers(spec: PyVal, data: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """Decode every `Annotated[bytes, Base64()]` field out of its base64 text."""
    out: PyVal = data
    if pyval_kind(data) != "dict":
        return out
    for f in spec["fields"]:
        if _has_marker(f, "Base64"):
            key: str = _read_key(_config(spec), f, out)
            if _has(out, key):
                cur: PyVal = out[key]
                if pyval_kind(cur) == "str":
                    ok: bool = True
                    raw: bytes = b""
                    try:
                        raw = b64decode(str(cur).encode("utf-8"), None, True)
                    except ValueError:
                        ok = False
                    if ok:
                        out = _replaced(out, key, raw)
                    else:
                        errs.append(_err("base64_decode", [key],
                                         "Base64 decoding error", cur))
    return out


def _is_root(spec: PyVal) -> bool:
    """True for a root model: a model whose only field is named `root`."""
    n: int = 0
    ok: bool = False
    for f in spec["fields"]:
        n = n + 1
        if str(f["name"]) == "root":
            ok = True
    return ok and n == 1


def _custom_entry(text: str, loc: PyVal, v: PyVal) -> PyVal:
    """Split a `PydanticCustomError` payload (`kind: message`) into an error entry."""
    at: int = text.find(": ")
    if at < 0:
        return _err("value_error", loc, f"Value error, {text}", v)
    return _err(text[:at], loc, text[at + 2:], v)


def _hook_key(spec: PyVal, name: str, data: PyVal) -> str:
    """The input key a hooked field is read from."""
    f: PyVal = _field_spec(spec, name)
    if pyval_kind(f) != "dict":
        return name
    return _read_key(_config(spec), f, data)


def _revalidated(spec: PyVal, name: str, v: PyVal, errs: Mut[list[PyVal]]) -> PyVal:
    """Re-check a value an `after` field validator returned against the field's type."""
    f: PyVal = _field_spec(spec, name)
    if pyval_kind(f) != "dict":
        return v
    fl: list[PyVal] = [name]
    t: PyVal = f["type"]
    before: int = len(errs)
    cv: PyVal = _val_value(t, v, fl, errs, _built_specs(spec))
    if len(errs) == before:
        _apply_meta(_get(f, "meta"), _bare_kind(t), cv, fl, errs)
    return cv


def _is_hook(h: PyVal, kind: str, mode: str) -> bool:
    """True when a hook record is of the given kind and mode."""
    return str(h["kind"]) == kind and str(h["mode"]) == mode


def _kept_errs(errs: Ref[list[PyVal]], names: Ref[list[str]]) -> list[PyVal]:
    """Errors not belonging to a plain-validated field (plain bypasses coercion)."""
    out: list[PyVal] = []
    for e in errs:
        loc: PyVal = e["loc"]
        skip: bool = False
        if len(loc) > 0:
            head: str = str(loc[0])
            for n in names:
                if n == head:
                    skip = True
        if not skip:
            out.append(e)
    return out


def _hook_args(h: PyVal) -> int:
    """How many arguments a hook method takes besides its receiver."""
    if not _has(h, "args"):
        return 1
    return int(h["args"])


def _info(name: str, data: PyVal, cfg: PyVal, context: PyVal = None) -> PyVal:
    """The ValidationInfo mapping handed to a two-argument validator."""
    out: dict[str, PyVal] = {"field_name": name, "data": data, "config": cfg,
                             "context": context}
    return out


def _serializes(h: PyVal, name: str) -> bool:
    """True when a serializer hook covers the named field."""
    if str(h["kind"]) != "serializer":
        return False
    for f in h["fields"]:
        if str(f) == name:
            return True
    return False


def _loc_text(loc: PyVal) -> str:
    """Render an error location the way pydantic does: `items.0.name`."""
    parts: list[str] = []
    if pyval_kind(loc) == "list":
        for p in loc:
            parts.append(str(p))
    return ".".join(parts)


def _message(title: str, errs: Ref[list[PyVal]]) -> str:
    """pydantic's multi-line ValidationError text."""
    n: int = len(errs)
    lines: list[str] = [f"{_plural(n, 'validation error')} for {title}"]
    for e in errs:
        where: str = _loc_text(e["loc"])
        if len(where) > 0:
            lines.append(where)
        given: PyVal = e["input"]
        lines.append(f"  {e['msg']} [type={e['type']}, input_value={given!r}, "
                     f"input_type={pyval_kind(given)}]")
    return "\n".join(lines)


def _u4(n: int) -> str:
    """A \\uXXXX escape for one code unit."""
    return "\\u" + HEX[n // 4096 % 16] + HEX[n // 256 % 16] + HEX[n // 16 % 16] + HEX[n % 16]


def _escape(s: str) -> str:
    """JSON-escape a string, leaving non-ASCII as UTF-8 (pydantic's JSON output)."""
    parts: list[str] = ['"']
    for c in s:
        if c == '"':
            parts.append('\\"')
        elif c == "\\":
            parts.append("\\\\")
        elif c == "\n":
            parts.append("\\n")
        elif c == "\t":
            parts.append("\\t")
        elif c == "\r":
            parts.append("\\r")
        elif c == chr(8):
            parts.append("\\b")
        elif c == chr(12):
            parts.append("\\f")
        else:
            n: int = ord(c)
            if n < 32:
                parts.append(_u4(n))
            else:
                parts.append(c)
    parts.append('"')
    return "".join(parts)


def _dumps(v: PyVal) -> str:
    """Compact JSON for a PyVal, matching pydantic's `model_dump_json` separators."""
    k: str = pyval_kind(v)
    if k == "NoneType":
        return "null"
    if k == "bool":
        return "true" if bool(v) else "false"
    if k == "int":
        return str(v)
    if k == "float":
        f: float = float(v)
        return f"{f}"
    if k == "str":
        return _escape(str(v))
    if k == "list":
        items: list[str] = []
        for x in v:
            items.append(_dumps(x))
        return "[" + ",".join(items) + "]"
    if k == "dict":
        parts: list[str] = []
        for key in v:
            parts.append(_escape(str(key)) + ":" + _dumps(v[key]))
        return "{" + ",".join(parts) + "}"
    raise TypeError(f"Object of type {k} is not JSON serializable")


def _out_field(f: PyVal, v: PyVal, by_alias: bool, specs: PyVal = None) -> PyVal:
    """The serialized form of one dumped field, honouring its Annotated markers."""
    out: PyVal = _out_value(f["type"], v, by_alias, specs)
    if _has_marker(f, "Base64") and pyval_kind(out) == "bytes":
        return b64encode(bytes(out)).decode("utf-8")
    return out


def _out_model(spec: PyVal, d: PyVal, by_alias: bool, specs: PyVal = None) -> dict[str, PyVal]:
    """A dumped model's keys after aliasing, ISO formatting and `Field(exclude=True)`."""
    sp: PyVal = specs
    if pyval_kind(sp) != "dict":
        sp = _built_specs(spec)
    out: dict[str, PyVal] = {}
    flds: PyVal = spec["fields"]
    names: list[str] = []
    for f in flds:
        name: str = str(f["name"])
        names.append(name)
        if not _has(d, name):
            continue
        meta: PyVal = _get(f, "meta")
        if _has(meta, "exclude") and bool(meta["exclude"]):
            continue
        out[_output_key(f) if by_alias else name] = _out_field(f, d[name], by_alias, sp)
    for extra in d:
        if not _listed(names, str(extra)):
            out[str(extra)] = d[extra]
    return out


def _out_value(t: PyVal, v: PyVal, by_alias: bool, specs: PyVal = None) -> PyVal:
    """The serialized form of one dumped value."""
    k: str = str(t["k"])
    if k == "optional":
        if pyval_kind(v) == "NoneType":
            return None
        return _out_value(t["inner"], v, by_alias, specs)
    if k == "model":
        if pyval_kind(v) != "dict":
            return v
        fmt: str = _fmt_of(t)
        if fmt == "duration":
            return _duration_secs(v)
        if fmt != "":
            return _iso_text(fmt, v)
        return _out_model(_resolved(t, specs), v, by_alias, specs)
    if k == "list" or k == "tuple" or k == "set":
        if pyval_kind(v) != "list":
            return v
        items: list[PyVal] = []
        i: int = 0
        for x in v:
            if k == "tuple":
                items.append(_out_value(t["items"][i], x, by_alias, specs))
            else:
                items.append(_out_value(t["elem"], x, by_alias, specs))
            i += 1
        return items
    if k == "union":
        member: PyVal = _member_spec(t, v)
        if pyval_kind(member) == "NoneType":
            return v
        return _out_value(member, v, by_alias, specs)
    if k == "dict":
        if pyval_kind(v) != "dict":
            return v
        out: dict[str, PyVal] = {}
        vt: PyVal = t["value"]
        for key in v:
            out[str(key)] = _out_value(vt, v[key], by_alias, specs)
        return out
    return v


def _drop_none_value(v: PyVal) -> PyVal:
    """Recursively drop None-valued keys from a dumped value."""
    if pyval_kind(v) != "dict":
        return v
    out: dict[str, PyVal] = {}
    for key in v:
        item: PyVal = v[key]
        if pyval_kind(item) == "NoneType":
            continue
        out[str(key)] = _drop_none_value(item)
    return out


def _drop_none(v: PyVal) -> dict[str, PyVal]:
    """A dumped model without its None-valued keys (exclude_none=True)."""
    out: dict[str, PyVal] = {}
    for key in v:
        item: PyVal = v[key]
        if pyval_kind(item) == "NoneType":
            continue
        out[str(key)] = _drop_none_value(item)
    return out


def _title_of(name: str) -> str:
    """pydantic's generated schema title: `first_name` -> `First Name`."""
    words: list[str] = []
    for part in name.split("_"):
        if len(part) > 0:
            words.append(part[0].upper() + part[1:])
    return " ".join(words)


def _type_json(t: PyVal, defs: Mut[dict[str, PyVal]], by_alias: bool = True,
               specs: PyVal = None) -> PyVal:
    """JSON Schema for one field type, collecting nested models into $defs."""
    k: str = str(t["k"])
    if k == "int":
        out_i: dict[str, PyVal] = {"type": "integer"}
        return out_i
    if k == "float":
        out_f: dict[str, PyVal] = {"type": "number"}
        return out_f
    if k == "bool":
        out_b: dict[str, PyVal] = {"type": "boolean"}
        return out_b
    if k == "str":
        out_s: dict[str, PyVal] = {"type": "string"}
        return out_s
    if k == "bytes":
        out_y: dict[str, PyVal] = {"format": "base64url", "type": "string"}
        return out_y
    if k == "none":
        out_n: dict[str, PyVal] = {"type": "null"}
        return out_n
    if k == "PyVal":
        out_a: dict[str, PyVal] = {}
        return out_a
    if k == "optional":
        nul: dict[str, PyVal] = {"type": "null"}
        alts: list[PyVal] = [_type_json(t["inner"], defs, by_alias, specs), nul]
        out_o: dict[str, PyVal] = {"anyOf": alts}
        return out_o
    if k == "list":
        out_l: dict[str, PyVal] = {"items": _type_json(t["elem"], defs, by_alias, specs),
                                   "type": "array"}
        return out_l
    if k == "dict":
        out_d: dict[str, PyVal] = {"additionalProperties":
                                   _type_json(t["value"], defs, by_alias, specs),
                                   "type": "object"}
        return out_d
    if k == "tuple":
        prefix: list[PyVal] = []
        items: PyVal = t["items"]
        for s in items:
            prefix.append(_type_json(s, defs, by_alias, specs))
        out_t: dict[str, PyVal] = {"maxItems": len(items), "minItems": len(items),
                                   "prefixItems": prefix, "type": "array"}
        return out_t
    if k == "set":
        out_st: dict[str, PyVal] = {"items": _type_json(t["elem"], defs, by_alias, specs),
                                    "type": "array", "uniqueItems": True}
        return out_st
    if k == "union":
        opts: list[PyVal] = []
        for m in t["members"]:
            opts.append(_type_json(m, defs, by_alias, specs))
        out_u: dict[str, PyVal] = {"anyOf": opts}
        return out_u
    if k == "enum":
        ename: str = str(t["class"])
        if not _has(defs, ename):
            evals: list[PyVal] = []
            for x in t["values"]:
                evals.append(x)
            body_e: dict[str, PyVal] = {"enum": evals, "title": ename,
                                       "type": "integer" if str(t["base"]) == "int"
                                       else "string"}
            defs[ename] = body_e
        out_e: dict[str, PyVal] = {"$ref": f"#/$defs/{ename}"}
        return out_e
    if k == "model":
        fmt: str = _fmt_of(t)
        if fmt == "duration":
            out_du: dict[str, PyVal] = {"type": "number"}
            return out_du
        if fmt == "secret":
            out_sec: dict[str, PyVal] = {"format": "password", "type": "string",
                                         "writeOnly": True}
            return out_sec
        if fmt != "":
            out_ts: dict[str, PyVal] = {"format": fmt, "type": "string"}
            return out_ts
        cname: str = str(t["class"])
        if not _has(defs, cname):
            placeholder: dict[str, PyVal] = {}
            defs[cname] = placeholder
            body: PyVal = _model_json(_resolved(t, specs), defs, None, by_alias, specs)
            defs[cname] = body
        out_m: dict[str, PyVal] = {"$ref": f"#/$defs/{cname}"}
        return out_m
    out_x: dict[str, PyVal] = {}
    return out_x


def _prop_json(f: PyVal, defs: Mut[dict[str, PyVal]], by_alias: bool = True,
               specs: PyVal = None) -> PyVal:
    """JSON Schema for one field, including its Field() keywords."""
    t: PyVal = f["type"]
    body: PyVal = _type_json(t, defs, by_alias, specs)
    out: dict[str, PyVal] = {}
    for key in body:
        out[str(key)] = body[key]
    meta: PyVal = _get(f, "meta")
    pairs: list[str] = ["gt", "exclusiveMinimum", "ge", "minimum", "lt", "exclusiveMaximum",
                        "le", "maximum", "multiple_of", "multipleOf",
                        "min_length", "minLength", "max_length", "maxLength",
                        "pattern", "pattern", "description", "description",
                        "examples", "examples"]
    i: int = 0
    while i < len(pairs):
        if _has(meta, pairs[i]):
            out[pairs[i + 1]] = meta[pairs[i]]
        i += 2
    if bool(f["has_default"]) and _has(f, "default"):
        out["default"] = f["default"]
    if _has(meta, "title"):
        out["title"] = meta["title"]
    else:
        out["title"] = _title_of(str(f["name"]))
    if _has(meta, "json_schema_extra"):
        extra: PyVal = meta["json_schema_extra"]
        if pyval_kind(extra) == "dict":
            for xk in extra:
                out[str(xk)] = extra[xk]
    return out


def _computed_json(hook: PyVal, defs: Mut[dict[str, PyVal]], by_alias: bool = True,
                   specs: PyVal = None) -> PyVal:
    """JSON Schema for one @computed_field property, from its return annotation."""
    body: PyVal = _type_json(_get(hook, "ret"), defs, by_alias, specs)
    out: dict[str, PyVal] = {}
    for key in body:
        out[str(key)] = body[key]
    out["readOnly"] = True
    out["title"] = _title_of(str(hook["method"]))
    return out


def _model_json(spec: PyVal, defs: Mut[dict[str, PyVal]], hooks: PyVal = None,
                by_alias: bool = True, specs: PyVal = None) -> PyVal:
    """JSON Schema object body for one model, plus its computed fields when hooks are given."""
    props: dict[str, PyVal] = {}
    required: list[PyVal] = []
    flds: PyVal = spec["fields"]
    for f in flds:
        key: str = _output_key(f) if by_alias else str(f["name"])
        props[key] = _prop_json(f, defs, by_alias, specs)
        if not bool(f["has_default"]):
            required.append(key)
    if pyval_kind(hooks) == "list":
        for h in hooks:
            if str(h["kind"]) == "computed" and _has(h, "ret"):
                name: str = str(h["method"])
                props[name] = _computed_json(h, defs, by_alias, specs)
                required.append(name)
    out: dict[str, PyVal] = {"properties": props}
    if len(required) > 0:
        out["required"] = required
    out["title"] = str(spec["class"])
    out["type"] = "object"
    return out


def _schema_json(spec: PyVal, hooks: PyVal = None, by_alias: bool = True) -> PyVal:
    """The full JSON Schema document for a model, with $defs for nested models.

    Passing the model's hook table adds its `@computed_field` properties, which is
    pydantic's `mode="serialization"` schema.
    """
    defs: dict[str, PyVal] = {}
    body: PyVal = _model_json(spec, defs, hooks, by_alias, _built_specs(spec))
    if len(defs) == 0:
        return body
    out: dict[str, PyVal] = {"$defs": defs}
    for key in body:
        out[str(key)] = body[key]
    return out


def _merged(base: PyVal, update: PyVal) -> PyVal:
    """A dumped model dict with `update`'s keys applied on top."""
    out: dict[str, PyVal] = {}
    for k in base:
        out[str(k)] = base[k]
    if pyval_kind(update) == "dict":
        for k2 in update:
            out[str(k2)] = update[k2]
    return out


def _kv_text(d: PyVal) -> str:
    """pydantic's `str(model)`: space-separated `field=value` pairs."""
    parts: list[str] = []
    for k in d:
        v: PyVal = d[k]
        parts.append(f"{k}={v!r}")
    return " ".join(parts)


def _validated(schema_text: str, obj: PyVal) -> PyVal:
    """Validate `obj` against a field-table JSON string, raising ValidationError."""
    spec: PyVal = loads(schema_text)
    errs: list[PyVal] = []
    root: list[PyVal] = []
    data: PyVal = _val_model(spec, obj, root, errs)
    if len(errs) > 0:
        raise ValidationError(_message(str(spec["class"]), errs))
    return data


def _raise_errors(cname: str, errs: Ref[list[PyVal]]) -> None:
    """Raise a pydantic-shaped ValidationError when any errors were collected."""
    if len(errs) > 0:
        raise ValidationError(_message(cname, errs))


def _error_list(schema_text: str, obj: PyVal) -> list[PyVal]:
    """Every validation error for `obj`, without raising."""
    spec: PyVal = loads(schema_text)
    errs: list[PyVal] = []
    root: list[PyVal] = []
    data: PyVal = obj
    if _is_root(spec) and not _has(obj, "root"):
        wrapped: dict[str, PyVal] = {"root": obj}
        data = wrapped
    data = _json_markers(spec, data, errs)
    data = _b64_markers(spec, data, errs)
    dropped: PyVal = _val_model(spec, data, root, errs)
    return errs


def _fields_present(schema_text: str, obj: PyVal) -> list[str]:
    """The field names an input mapping supplies explicitly."""
    spec: PyVal = loads(schema_text)
    out: list[str] = []
    if pyval_kind(obj) != "dict":
        return out
    cfg: PyVal = _config(spec)
    for f in spec["fields"]:
        key: str = _read_key(cfg, f, obj)
        if _has(obj, key):
            out.append(str(f["name"]))
    return out


def _json_error_list(schema_text: str, text: str) -> list[PyVal]:
    """Every validation error for a JSON document, without raising."""
    obj: PyVal = None
    try:
        obj = loads(text)
    except ValueError as exc:
        loc: list[PyVal] = []
        bad: dict[str, PyVal] = {"type": "json_invalid", "loc": loc,
                                 "msg": f"Invalid JSON: {exc}", "input": text}
        out: list[PyVal] = [bad]
        return out
    return _error_list(schema_text, obj)


def _json_or_raise(schema_text: str, text: str) -> PyVal:
    """Decode JSON, reporting a bad document as a pydantic-shaped ValidationError."""
    spec: PyVal = loads(schema_text)
    cname: str = str(spec["class"])
    try:
        return loads(text)
    except ValueError as exc:
        raise ValidationError(f"1 validation error for {cname}\n  Invalid JSON: {exc} "
                              f"[type=json_invalid, input_value={text!r}, input_type=str]")


@dataclass
class BaseModel:
    """Base class for models: subclass it and declare annotated fields."""

    def model_dump(self: Ref[BaseModel], by_alias: bool = False,
                   exclude_none: bool = False) -> PyVal:
        """This model as a plain dict, with nested models inlined.

        Field serializers rewrite their fields, computed fields are appended, and a
        `@model_serializer` replaces the whole result.
        """
        hooks: PyVal = loads(hooks_json(self))["hooks"]
        data: dict[str, PyVal] = fields_of(self)
        rootish: bool = len(data) == 1 and _has(data, "root")
        for hs in hooks:
            for fs in hs["fields"]:
                sname: str = str(fs)
                if _serializes(hs, sname) and _has(data, sname):
                    sval: PyVal = data[sname]
                    data[sname] = run_hook_val(self, str(hs["method"]), sval)
        for hc in hooks:
            if str(hc["kind"]) == "computed":
                data[str(hc["method"])] = run_hook_get(self, str(hc["method"]))
        for hm in hooks:
            if str(hm["kind"]) == "modelser":
                return run_hook_get(self, str(hm["method"]))
        if rootish:
            return data["root"]
        spec: PyVal = loads(fields_json(self))
        shaped: dict[str, PyVal] = _out_model(spec, data, by_alias)
        if by_alias:
            gen: str = _cfg_fn(_config(spec), "alias_generator")
            if gen != "":
                for fg in spec["fields"]:
                    nm: str = str(fg["name"])
                    if _output_key(fg) == nm:
                        shaped = _renamed(shaped, nm, str(run_hook(self, gen, nm)))
        if exclude_none:
            return _drop_none(shaped)
        return shaped

    def model_dump_json(self: Ref[BaseModel], by_alias: bool = False,
                        exclude_none: bool = False) -> str:
        """This model as compact JSON."""
        return _dumps(self.model_dump(by_alias, exclude_none))

    def model_copy(self: Ref[BaseModel], update: PyVal = None) -> Self:
        """A copy of this model, with `update`'s keys replaced (no validation)."""
        return fields_build(self, _merged(fields_of(self), update))

    def dict(self: Ref[BaseModel]) -> dict[str, PyVal]:
        """pydantic v1 alias for model_dump()."""
        return fields_of(self)

    def json(self: Ref[BaseModel]) -> str:
        """pydantic v1 alias for model_dump_json()."""
        return _dumps(fields_of(self))

    def __str__(self: Ref[BaseModel]) -> str:
        """pydantic's `id=1 name='ada'` rendering."""
        return _kv_text(fields_of(self))

    def __setattr__(self: Mut[BaseModel], name: str, value: PyVal) -> None:
        """Field assignment, honouring `frozen` and `validate_assignment` in model_config."""
        spec: PyVal = loads(fields_json(self))
        cfg: PyVal = _config(spec)
        errs: list[PyVal] = []
        if _cfg_bool(cfg, "frozen"):
            errs.append(_err("frozen_instance", [name], "Instance is frozen", value))
            _raise_errors(str(spec["class"]), errs)
        out: PyVal = value
        if _cfg_bool(cfg, "validate_assignment"):
            out = _val_field(spec, name, value, errs)
            _raise_errors(str(spec["class"]), errs)
        fields_set(self, name, out)

    @classmethod
    def model_validate(cls, obj: PyVal, context: PyVal = None) -> Self:
        """Validate a mapping into an instance of this model, running its validators."""
        spec: PyVal = loads(fields_json(cls))
        hooks: PyVal = loads(hooks_json(cls))["hooks"]
        errs: list[PyVal] = []
        root: list[PyVal] = []
        data: PyVal = obj
        if _is_root(spec) and not _has(obj, "root"):
            wrapped: dict[str, PyVal] = {"root": obj}
            data = wrapped
        data = _json_markers(spec, data, errs)
        data = _b64_markers(spec, data, errs)
        gen: str = _cfg_fn(_config(spec), "alias_generator")
        if gen != "" and pyval_kind(data) == "dict":
            for fg in spec["fields"]:
                gname: str = str(fg["name"])
                if _input_key(fg) == gname and not _has(data, gname):
                    gkey: str = str(run_hook(cls, gen, gname))
                    if _has(data, gkey):
                        data = _replaced(data, gname, data[gkey])
        for h in hooks:
            if _is_hook(h, "model", "before"):
                try:
                    if _hook_args(h) == 2:
                        data = run_hook_info(cls, str(h["method"]), data,
                                             _info("", data, _config(spec), context))
                    else:
                        data = run_hook(cls, str(h["method"]), data)
                except PydanticCustomError as pce:
                    errs.append(_custom_entry(f"{pce}", root, data))
                except ValueError as exc:
                    errs.append(_err("value_error", root, f"Value error, {exc}", data))
        for hf in hooks:
            if _is_hook(hf, "field", "before") and len(errs) == 0:
                for fname in hf["fields"]:
                    key: str = _hook_key(spec, str(fname), data)
                    if _has(data, key):
                        raw: PyVal = data[key]
                        try:
                            bval: PyVal = raw
                            if _hook_args(hf) == 2:
                                bval = run_hook_info(cls, str(hf["method"]), raw,
                                                     _info(str(fname), data,
                                                           _config(spec), context))
                            else:
                                bval = run_hook(cls, str(hf["method"]), raw)
                            data = _replaced(data, key, bval)
                        except PydanticCustomError as pce2:
                            errs.append(_custom_entry(f"{pce2}", [key], raw))
                        except ValueError as exc2:
                            errs.append(_err("value_error", [key],
                                             f"Value error, {exc2}", raw))
        plain_names: list[str] = []
        plain_vals: dict[str, PyVal] = {}
        for hp in hooks:
            if _is_hook(hp, "field", "plain") and len(errs) == 0:
                for pname in hp["fields"]:
                    pkey: str = _hook_key(spec, str(pname), data)
                    if _has(data, pkey):
                        praw: PyVal = data[pkey]
                        try:
                            pval: PyVal = praw
                            if _hook_args(hp) == 2:
                                pval = run_hook_info(cls, str(hp["method"]), praw,
                                                     _info(str(pname), data,
                                                           _config(spec), context))
                            else:
                                pval = run_hook(cls, str(hp["method"]), praw)
                            plain_names.append(str(pname))
                            plain_vals[str(pname)] = pval
                        except PydanticCustomError as pce5:
                            errs.append(_custom_entry(f"{pce5}", [pkey], praw))
                        except ValueError as exc5:
                            errs.append(_err("value_error", [pkey],
                                             f"Value error, {exc5}", praw))
        coerced: PyVal = data
        if len(errs) == 0:
            for fb in spec["fields"]:
                bkey: str = _read_key(_config(spec), fb, data)
                for bfn in _marker_fns(fb, "BeforeValidator"):
                    if _has(data, bkey) and len(errs) == 0:
                        braw: PyVal = data[bkey]
                        try:
                            data = _replaced(data, bkey, run_hook(cls, bfn, braw))
                        except ValueError as bexc:
                            errs.append(_err("value_error", [bkey],
                                             f"Value error, {bexc}", braw))
        if len(errs) == 0:
            coerced = _val_model(spec, data, root, errs)
            if len(plain_names) > 0:
                kept: list[PyVal] = _kept_errs(errs, plain_names)
                while len(errs) > 0:
                    gone: PyVal = errs.pop()
                for kp in kept:
                    errs.append(kp)
                for pn in plain_names:
                    coerced = _replaced(coerced, pn, plain_vals[pn])
        if len(errs) == 0:
            for fa in spec["fields"]:
                aname2: str = str(fa["name"])
                for afn in _marker_fns(fa, "AfterValidator"):
                    if _has(coerced, aname2) and len(errs) == 0:
                        acur: PyVal = coerced[aname2]
                        try:
                            aout: PyVal = run_hook(cls, afn, acur)
                            coerced = _replaced(coerced, aname2,
                                                _revalidated(spec, aname2, aout, errs))
                        except ValueError as aexc:
                            errs.append(_err("value_error", [aname2],
                                             f"Value error, {aexc}", acur))
        for ha in hooks:
            if _is_hook(ha, "field", "after") and len(errs) == 0:
                for aname in ha["fields"]:
                    nm: str = str(aname)
                    if _has(coerced, nm):
                        cur: PyVal = coerced[nm]
                        try:
                            out: PyVal = cur
                            if _hook_args(ha) == 2:
                                out = run_hook_info(cls, str(ha["method"]), cur,
                                                    _info(nm, coerced, _config(spec),
                                                          context))
                            else:
                                out = run_hook(cls, str(ha["method"]), cur)
                            coerced = _replaced(coerced, nm,
                                                _revalidated(spec, nm, out, errs))
                        except PydanticCustomError as pce3:
                            errs.append(_custom_entry(f"{pce3}", [nm], cur))
                        except ValueError as exc3:
                            errs.append(_err("value_error", [nm],
                                             f"Value error, {exc3}", cur))
        _raise_errors(str(spec["class"]), errs)
        inst: Self = fields_build(cls, coerced)
        for hm in hooks:
            if _is_hook(hm, "model", "after") and len(errs) == 0:
                try:
                    run_hook_self(inst, str(hm["method"]))
                except PydanticCustomError as pce4:
                    errs.append(_custom_entry(f"{pce4}", root, coerced))
                except ValueError as exc4:
                    errs.append(_err("value_error", root, f"Value error, {exc4}", coerced))
        _raise_errors(str(spec["class"]), errs)
        return inst

    @classmethod
    def model_validate_json(cls, text: str, context: PyVal = None) -> Self:
        """Validate a JSON document into an instance of this model."""
        return cls.model_validate(_json_or_raise(fields_json(cls), text), context)

    @classmethod
    def model_validate_errors(cls, obj: PyVal) -> list[PyVal]:
        """Every validation error for `obj` as `{type, loc, msg, input}` dicts."""
        return _error_list(fields_json(cls), obj)

    @classmethod
    def model_validate_json_errors(cls, text: str) -> list[PyVal]:
        """Every validation error for a JSON document, `json_invalid` when it does not parse."""
        return _json_error_list(fields_json(cls), text)

    @classmethod
    def model_fields_set(cls, obj: PyVal) -> list[str]:
        """The field names `obj` supplies explicitly (a classmethod, not an instance attribute)."""
        return _fields_present(fields_json(cls), obj)

    @classmethod
    def model_construct(cls, values: PyVal) -> Self:
        """Build an instance without validation; values must already have field types."""
        return fields_build(cls, values)

    @classmethod
    def model_json_schema(cls, mode: str = "validation", by_alias: bool = True) -> PyVal:
        """The JSON Schema for this model (draft 2020-12, pydantic-shaped).

        `mode="serialization"` adds the model's `@computed_field` properties;
        `by_alias=False` keys the properties by field name instead of alias.
        """
        if mode == "serialization":
            return _schema_json(loads(fields_json(cls)), loads(hooks_json(cls))["hooks"],
                                by_alias)
        return _schema_json(loads(fields_json(cls)), None, by_alias)

    @classmethod
    def model_fields(cls) -> PyVal:
        """This model's field table: name, type, default and Field() metadata."""
        return loads(fields_json(cls))["fields"]

    @classmethod
    def parse_obj(cls, obj: PyVal) -> Self:
        """pydantic v1 alias for model_validate()."""
        return cls.model_validate(obj)

    @classmethod
    def parse_raw(cls, text: str) -> Self:
        """pydantic v1 alias for model_validate_json()."""
        return cls.model_validate(_json_or_raise(fields_json(cls), text))

    @classmethod
    def schema(cls) -> PyVal:
        """pydantic v1 alias for model_json_schema()."""
        return _schema_json(loads(fields_json(cls)), None)
