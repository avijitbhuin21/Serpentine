"""serp-scales (Scales) — a pandas-style DataFrame / Series library in pure Serpentine.

Columns are ``list[PyVal]`` (heterogeneous cells, ``None`` = missing), the index is a
``list[PyVal]`` of labels, and every operation returns a fresh object. The API mirrors
pandas under a ``serp_scales`` import root: ``DataFrame``/``Series`` constructors,
``df["col"]``, ``df["new"] = ...``, ``df.loc[mask]``, ``df.iloc[i]``, comparison masks
(``s > 1``, ``&``/``|``/``~``), arithmetic, reductions, ``sort_values``, ``groupby``
(``sum``/``mean``/``count``/``agg``...), ``merge``, ``concat``, ``fillna``/``dropna``,
``apply``/``map``, ``value_counts``, the ``.str`` accessor, ``read_csv``/``to_csv`` and
``to_dict``. The same source runs under CPython (via the serpentine shim) and compiles
natively with ``serp``; see README.md for the divergences from pandas.
"""
from __future__ import annotations
from typing import Callable, Optional, overload
from serpentine import Ref, Mut, Owned, dataclass, PyVal, pyval_kind, move
from serp_json import dumps as _json_dumps, loads as _json_loads
from serp_datetime import Dt, parse_iso, iso_format, make, weekday as _dt_weekday, \
    day_of_year as _dt_doy, days_in_month as _dt_dim, days_from_civil as _days_from_civil

DT_TAG: str = "\x01D"
MAX_ROWS: int = 60
MAX_COLUMNS: int = 20


def _day_name(i: int) -> str:
    """English weekday name (0 = Monday)."""
    names: list[str] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                        "Sunday"]
    return names[i]


def _month_name(m: int) -> str:
    """English month name (1 = January)."""
    names: list[str] = ["January", "February", "March", "April", "May", "June", "July",
                        "August", "September", "October", "November", "December"]
    return names[m - 1]


# ----------------------------------------------------------------------------- cells


def _is_dt(v: PyVal) -> bool:
    """True for a datetime cell (tagged ISO text)."""
    if pyval_kind(v) != "str":
        return False
    s: str = str(v)
    return len(s) > 2 and s[:2] == DT_TAG


def _dt_iso(v: PyVal) -> str:
    """ISO text of a datetime cell without the tag."""
    return str(v)[2:]


def _dt_cell(d: Ref[Dt]) -> PyVal:
    """Datetime cell from a Dt."""
    return DT_TAG + iso_format(d)


def _dt_parse(v: PyVal) -> Dt:
    """Dt of a datetime cell."""
    return parse_iso(_dt_iso(v))


def _dt_text(v: PyVal, with_time: bool) -> str:
    """Display text of a datetime cell (date only unless with_time)."""
    iso: str = _dt_iso(v)
    if with_time:
        return iso[:10] + " " + iso[11:]
    return iso[:10]


def _dt_norm(v: PyVal) -> str:
    """Comparable ISO text for a datetime cell or a date-like string."""
    if _is_dt(v):
        return _dt_iso(v)
    d: Dt = parse_iso(str(v))
    return iso_format(d)


def _cell_out(v: PyVal) -> PyVal:
    """Cell as handed to user code: datetime cells become 'YYYY-MM-DD HH:MM:SS' text."""
    if _is_dt(v):
        return _dt_text(v, True)
    return v


def _cells_out(vals: Ref[list[PyVal]]) -> list[PyVal]:
    """User-facing copies of a cell list."""
    out: list[PyVal] = []
    for v in vals:
        out.append(_cell_out(v))
    return out


def isna(v: PyVal) -> bool:
    """True for a missing cell (None or a float NaN)."""
    k: str = pyval_kind(v)
    if k == "NoneType":
        return True
    if k == "float":
        f: float = float(v)
        return f != f
    return False


def notna(v: PyVal) -> bool:
    """True for a present cell."""
    return not isna(v)


def _is_num(v: PyVal) -> bool:
    """True when the cell is an int, float or bool."""
    k: str = pyval_kind(v)
    return k == "int" or k == "float" or k == "bool"


def _num(v: PyVal) -> float:
    """Numeric value of a cell as a float (bools count as 0/1)."""
    k: str = pyval_kind(v)
    if k == "bool":
        if v:
            return 1.0
        return 0.0
    if k == "int":
        return float(int(v))
    return float(v)


def _cmp(a: PyVal, b: PyVal) -> int:
    """Three-way compare of two cells: numbers by value, strings lexically, mixed kinds by
    kind name; missing cells sort last."""
    na_a: bool = isna(a)
    na_b: bool = isna(b)
    if na_a and na_b:
        return 0
    if na_a:
        return 1
    if na_b:
        return -1
    ka: str = pyval_kind(a)
    kb: str = pyval_kind(b)
    if ka == "int" and kb == "int":
        ia: int = int(a)
        ib: int = int(b)
        if ia < ib:
            return -1
        if ia > ib:
            return 1
        return 0
    if _is_num(a) and _is_num(b):
        fa: float = _num(a)
        fb: float = _num(b)
        if fa < fb:
            return -1
        if fa > fb:
            return 1
        return 0
    if ka == "str" and kb == "str":
        sa: str = str(a)
        sb: str = str(b)
        if _is_dt(a) or _is_dt(b):
            sa = _dt_norm(a)
            sb = _dt_norm(b)
        if sa < sb:
            return -1
        if sa > sb:
            return 1
        return 0
    if ka != kb:
        if ka < kb:
            return -1
        return 1
    ra: str = str(a)
    rb: str = str(b)
    if ra < rb:
        return -1
    if ra > rb:
        return 1
    return 0


def _hkey(v: PyVal) -> str:
    """Hashable text key of a cell (kind-tagged so 1 and "1" stay distinct)."""
    if isna(v):
        return "~"
    return pyval_kind(v) + ":" + str(v)


def _row_key(cols: Ref[list[list[PyVal]]], i: int) -> str:
    """Hashable text key of row i across several key columns."""
    parts: list[str] = []
    for c in cols:
        parts.append(_hkey(c[i]))
    return "\x1f".join(parts)


def _dtype_of(vals: Ref[list[PyVal]]) -> str:
    """pandas-style dtype name inferred from the cells."""
    seen_f: bool = False
    seen_i: bool = False
    seen_b: bool = False
    seen_o: bool = False
    seen_na: bool = False
    seen_dt: bool = False
    for v in vals:
        k: str = pyval_kind(v)
        if k == "float":
            seen_f = True
        elif k == "int":
            seen_i = True
        elif k == "bool":
            seen_b = True
        elif k == "NoneType":
            seen_na = True
        elif _is_dt(v):
            seen_dt = True
        else:
            seen_o = True
    if seen_dt and not (seen_o or seen_f or seen_i or seen_b):
        return "datetime64[ns]"
    if seen_o or seen_dt:
        return "object"
    if seen_b and (seen_i or seen_f):
        return "object"
    if seen_f or (seen_na and seen_i):
        return "float64"
    if seen_i:
        return "int64"
    if seen_b:
        if seen_na:
            return "object"
        return "bool"
    return "object"


def _cast(v: PyVal, dtype: str) -> PyVal:
    """Convert one cell to the named dtype (missing cells stay missing)."""
    if isna(v):
        return None
    if dtype == "float64" or dtype == "float":
        if pyval_kind(v) == "str":
            return float(str(v).strip())
        return _num(v)
    if dtype == "int64" or dtype == "int":
        k: str = pyval_kind(v)
        if k == "str":
            return int(str(v).strip())
        if k == "float":
            return int(float(v))
        if k == "bool":
            if v:
                return 1
            return 0
        return v
    if dtype == "str" or dtype == "string" or dtype == "object":
        if pyval_kind(v) == "str":
            return v
        return str(v)
    if dtype == "bool":
        return bool(v)
    raise TypeError(f"data type '{dtype}' not understood")


def _fmt_float(f: float) -> str:
    """Display text of a float: up to 6 decimals, shortest repr."""
    if f != f:
        return "NaN"
    if f == 0.0:
        return "0.0"
    r: float = round(f, 6)
    return str(r)


def _decimals(s: str) -> int:
    """Number of digits after the decimal point in a plain float string."""
    dot: int = s.find(".")
    if dot < 0 or s.find("e") >= 0:
        return 0
    return len(s) - dot - 1


def _fmt_cells(vals: Ref[list[PyVal]], dtype: str) -> list[str]:
    """Display strings for a column, aligned the way pandas shows each dtype."""
    out: list[str] = []
    if dtype == "float64":
        maxd: int = 1
        raw: list[str] = []
        for v in vals:
            if isna(v):
                raw.append("NaN")
            else:
                t: str = _fmt_float(_num(v))
                raw.append(t)
                d: int = _decimals(t)
                if d > maxd:
                    maxd = d
        for t2 in raw:
            if t2 == "NaN" or t2.find("e") >= 0:
                out.append(t2)
            else:
                d2: int = _decimals(t2)
                pad: str = t2
                if d2 == 0:
                    pad = pad + "."
                while d2 < maxd:
                    pad = pad + "0"
                    d2 += 1
                out.append(pad)
        return out
    if dtype == "datetime64[ns]":
        with_time: bool = False
        for v3 in vals:
            if _is_dt(v3) and _dt_iso(v3)[11:] != "00:00:00":
                with_time = True
        for v4 in vals:
            if _is_dt(v4):
                out.append(_dt_text(v4, with_time))
            else:
                out.append("NaT")
        return out
    for v2 in vals:
        if pyval_kind(v2) == "NoneType":
            out.append("None")
        elif pyval_kind(v2) == "float":
            out.append(_fmt_float(float(v2)))
        elif _is_dt(v2):
            out.append(_dt_text(v2, True))
        else:
            out.append(str(v2))
    return out


def _ljust(s: str, w: int) -> str:
    """Left-justify text to width w."""
    out: str = s
    while len(out) < w:
        out = out + " "
    return out


def _rjust(s: str, w: int) -> str:
    """Right-justify text to width w."""
    out: str = s
    while len(out) < w:
        out = " " + out
    return out


def _labels(idx: Ref[list[PyVal]]) -> list[str]:
    """Display strings of index labels."""
    out: list[str] = []
    for v in idx:
        if pyval_kind(v) == "float":
            out.append(_fmt_float(float(v)))
        elif _is_dt(v):
            out.append(_dt_text(v, _dt_iso(v)[11:] != "00:00:00"))
        else:
            out.append(str(v))
    return out


def _width(items: Ref[list[str]]) -> int:
    """Longest string length in a list."""
    w: int = 0
    for s in items:
        if len(s) > w:
            w = len(s)
    return w


def _range_index(n: int) -> list[PyVal]:
    """Default 0..n-1 labels."""
    out: list[PyVal] = []
    for i in range(n):
        out.append(i)
    return out


def _shown_positions(n: int, limit: int, edge: int) -> list[int]:
    """Positions to display: all when n <= limit, else edge head, -1 (ellipsis), edge tail."""
    out: list[int] = []
    if n <= limit:
        for i in range(n):
            out.append(i)
        return out
    for i2 in range(edge):
        out.append(i2)
    out.append(-1)
    for i3 in range(n - edge, n):
        out.append(i3)
    return out


def _shown_rows(n: int) -> list[int]:
    """Row positions to display (pandas display.max_rows=60, min_rows=10)."""
    return _shown_positions(n, MAX_ROWS, 5)


def _shown_cols(n: int) -> list[int]:
    """Column positions to display (pandas display.max_columns=20)."""
    return _shown_positions(n, MAX_COLUMNS, 10)


def _unbox_list(data: PyVal) -> list[PyVal]:
    """Copy a PyVal list into a Serpentine list of cells."""
    out: list[PyVal] = []
    for v in data:
        out.append(v)
    return out


def _take(vals: Ref[list[PyVal]], pos: Ref[list[int]]) -> list[PyVal]:
    """Cells at the given positions."""
    out: list[PyVal] = []
    for p in pos:
        out.append(vals[p])
    return out


def _less(keys: Ref[list[list[PyVal]]], asc: Ref[list[bool]], i: int, j: int) -> bool:
    """Row-i-before-row-j under lexicographic column ordering (missing cells last)."""
    for c in range(len(keys)):
        a: PyVal = keys[c][i]
        b: PyVal = keys[c][j]
        na_a: bool = isna(a)
        na_b: bool = isna(b)
        if na_a and na_b:
            continue
        if na_a:
            return False
        if na_b:
            return True
        r: int = _cmp(a, b)
        if r != 0:
            if asc[c]:
                return r < 0
            return r > 0
    return False


def _argsort(keys: Ref[list[list[PyVal]]], asc: Ref[list[bool]], n: int) -> list[int]:
    """Stable merge sort of row positions by the key columns."""
    src: list[int] = []
    for i in range(n):
        src.append(i)
    if n < 2:
        return src
    buf: list[int] = []
    for i2 in range(n):
        buf.append(0)
    width: int = 1
    while width < n:
        lo: int = 0
        while lo < n:
            mid: int = lo + width
            if mid > n:
                mid = n
            hi: int = lo + 2 * width
            if hi > n:
                hi = n
            a: int = lo
            b: int = mid
            k: int = lo
            while a < mid and b < hi:
                if _less(keys, asc, src[b], src[a]):
                    buf[k] = src[b]
                    b += 1
                else:
                    buf[k] = src[a]
                    a += 1
                k += 1
            while a < mid:
                buf[k] = src[a]
                a += 1
                k += 1
            while b < hi:
                buf[k] = src[b]
                b += 1
                k += 1
            lo = hi
        for i3 in range(n):
            src[i3] = buf[i3]
        width = width * 2
    return src


def _arith(a: PyVal, b: PyVal, op: str) -> PyVal:
    """One arithmetic cell operation with pandas-like missing propagation."""
    if isna(a) or isna(b):
        return None
    ka: str = pyval_kind(a)
    kb: str = pyval_kind(b)
    if op == "+" and ka == "str" and kb == "str":
        return str(a) + str(b)
    if ka == "str" or kb == "str":
        raise TypeError(f"unsupported operand type(s) for {op}: '{ka}' and '{kb}'")
    both_int: bool = (ka == "int" or ka == "bool") and (kb == "int" or kb == "bool")
    if both_int and op != "/":
        ia: int = int(_num(a))
        ib: int = int(_num(b))
        if op == "+":
            return ia + ib
        if op == "-":
            return ia - ib
        if op == "*":
            return ia * ib
        if op == "//":
            if ib == 0:
                return None
            return ia // ib
        if op == "%":
            if ib == 0:
                return None
            return ia % ib
        if op == "**":
            if ib < 0:
                return float(ia) ** float(ib)
            return ia ** ib
    fa: float = _num(a)
    fb: float = _num(b)
    if op == "+":
        return fa + fb
    if op == "-":
        return fa - fb
    if op == "*":
        return fa * fb
    if op == "/":
        if fb == 0.0:
            return None
        return fa / fb
    if op == "//":
        if fb == 0.0:
            return None
        return fa // fb
    if op == "%":
        if fb == 0.0:
            return None
        return fa % fb
    return fa ** fb


def _compare(a: PyVal, b: PyVal, op: str) -> PyVal:
    """One comparison cell operation; missing cells compare False (except !=)."""
    if (_is_dt(a) or _is_dt(b)) and pyval_kind(a) == "str" and pyval_kind(b) == "str":
        same: bool = _dt_norm(a) == _dt_norm(b)
        if op == "==":
            return same
        if op == "!=":
            return not same
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if isna(a) or isna(b):
        return False
    r: int = _cmp(a, b)
    if op == "<":
        return r < 0
    if op == "<=":
        return r <= 0
    if op == ">":
        return r > 0
    return r >= 0


def _box_operand(other: Ref[int | float | str | Series]) -> PyVal:
    """Scalar operand as a cell (Series operands are handled by the caller)."""
    if isinstance(other, int):
        return other
    if isinstance(other, float):
        return other
    if isinstance(other, str):
        return other
    return None


def _quantile(sorted_vals: Ref[list[float]], q: float) -> float:
    """Linear-interpolated quantile of an ascending float list."""
    n: int = len(sorted_vals)
    if n == 0:
        return 0.0
    pos: float = (n - 1) * q
    lo: int = int(pos)
    hi: int = lo + 1
    if hi >= n:
        return sorted_vals[n - 1]
    frac: float = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _sorted_floats(vals: Ref[list[PyVal]]) -> list[float]:
    """Present numeric cells as an ascending float list."""
    out: list[float] = []
    for v in vals:
        if _is_num(v) and not isna(v):
            out.append(_num(v))
    out.sort()
    return out


def _same_labels(a: Ref[list[PyVal]], b: Ref[list[PyVal]]) -> bool:
    """True when two index label lists are identical position by position."""
    if len(a) != len(b):
        return False
    for i in range(len(a)):
        if a[i] != b[i]:
            return False
    return True


def _label_positions(idx: Ref[list[PyVal]]) -> dict[str, int]:
    """Position of each label by hash key (ValueError on duplicates)."""
    pos: dict[str, int] = {}
    for i in range(len(idx)):
        k: str = _hkey(idx[i])
        if k in pos:
            raise ValueError("cannot reindex on an axis with duplicate labels")
        pos[k] = i
    return pos


@dataclass
class _Aligned:
    index: list[PyVal]
    left: list[PyVal]
    right: list[PyVal]


def _align(ai: Ref[list[PyVal]], av: Ref[list[PyVal]], bi: Ref[list[PyVal]],
           bv: Ref[list[PyVal]]) -> _Aligned:
    """Cells of two labelled columns over the sorted union of their labels."""
    if _same_labels(ai, bi):
        return _Aligned([v for v in ai], [v for v in av], [v for v in bv])
    apos: dict[str, int] = _label_positions(ai)
    bpos: dict[str, int] = _label_positions(bi)
    labels: list[PyVal] = [v for v in ai]
    for j in range(len(bi)):
        if _hkey(bi[j]) not in apos:
            labels.append(bi[j])
    keys: list[list[PyVal]] = [[v for v in labels]]
    order: list[int] = _argsort(keys, [True], len(labels))
    idx: list[PyVal] = _take(labels, order)
    left: list[PyVal] = []
    right: list[PyVal] = []
    for lbl in idx:
        k: str = _hkey(lbl)
        if k in apos:
            left.append(av[apos[k]])
        else:
            left.append(None)
        if k in bpos:
            right.append(bv[bpos[k]])
        else:
            right.append(None)
    return _Aligned(move(idx), move(left), move(right))


def _pair_stats(xs: Ref[list[PyVal]], ys: Ref[list[PyVal]], op: str) -> PyVal:
    """Sample covariance or Pearson correlation over pairwise-present numeric cells."""
    n: int = 0
    sx: float = 0.0
    sy: float = 0.0
    for i in range(len(xs)):
        if notna(xs[i]) and notna(ys[i]) and _is_num(xs[i]) and _is_num(ys[i]):
            n += 1
            sx += _num(xs[i])
            sy += _num(ys[i])
    if n < 2:
        return None
    mx: float = sx / n
    my: float = sy / n
    sxy: float = 0.0
    sxx: float = 0.0
    syy: float = 0.0
    for i2 in range(len(xs)):
        if notna(xs[i2]) and notna(ys[i2]) and _is_num(xs[i2]) and _is_num(ys[i2]):
            dx: float = _num(xs[i2]) - mx
            dy: float = _num(ys[i2]) - my
            sxy += dx * dy
            sxx += dx * dx
            syy += dy * dy
    if op == "cov":
        return sxy / (n - 1)
    if sxx == 0.0 or syy == 0.0:
        return None
    return sxy / ((sxx * syy) ** 0.5)


def _window_agg(vals: Ref[list[PyVal]], window: int, min_periods: int, op: str) -> list[PyVal]:
    """Trailing-window aggregation of numeric cells (missing until min_periods present)."""
    out: list[PyVal] = []
    n: int = len(vals)
    for i in range(n):
        lo: int = i - window + 1
        if lo < 0:
            lo = 0
        if i + 1 < window and min_periods >= window:
            out.append(None)
            continue
        got: list[PyVal] = []
        for j in range(lo, i + 1):
            if notna(vals[j]) and _is_num(vals[j]):
                got.append(_num(vals[j]))
        if len(got) < min_periods or len(got) == 0:
            out.append(None)
        elif op == "count":
            out.append(len(got))
        else:
            out.append(_agg_cells(got, op))
    return out


# ----------------------------------------------------------------------------- Series


@dataclass
class Series:
    values: list[PyVal]
    index: list[PyVal]
    name: PyVal

    def __init__(self: Mut[Series], data: PyVal = None, index: PyVal = None,
                 name: PyVal = None, dtype: PyVal = None,
                 _v: Owned[Optional[list[PyVal]]] = None,
                 _i: Owned[Optional[list[PyVal]]] = None) -> None:
        vals: list[PyVal] = []
        idx: list[PyVal] = []
        if _v is not None:
            vals = move(_v)
        else:
            k: str = pyval_kind(data)
            if k == "list":
                vals = _unbox_list(data)
            elif k == "dict":
                for key in data:
                    idx.append(key)
                    vals.append(data[key])
            elif k != "NoneType":
                n: int = 1
                if pyval_kind(index) == "list":
                    n = len(index)
                for _ in range(n):
                    vals.append(data)
        if _i is not None:
            idx = move(_i)
        elif pyval_kind(index) == "list":
            idx = _unbox_list(index)
            if len(idx) != len(vals):
                raise ValueError(f"Length of values ({len(vals)}) does not match length of "
                                 f"index ({len(idx)})")
        elif len(idx) == 0:
            idx = _range_index(len(vals))
        if pyval_kind(dtype) == "str":
            vals = [_cast(v, str(dtype)) for v in vals]
        self.values = move(vals)
        self.index = move(idx)
        self.name = name

    # -- shape & access

    def __len__(self: Ref[Series]) -> int:
        return len(self.values)

    @property
    def size(self: Ref[Series]) -> int:
        return len(self.values)

    @property
    def empty(self: Ref[Series]) -> bool:
        return len(self.values) == 0

    @property
    def dtype(self: Ref[Series]) -> str:
        return _dtype_of(self.values)

    @property
    def iloc(self: Ref[Series]) -> _SeriesILoc:
        return _SeriesILoc([v for v in self.values], [v for v in self.index], self.name)

    @property
    def loc(self: Ref[Series]) -> _SeriesLoc:
        return _SeriesLoc([v for v in self.values], [v for v in self.index], self.name)

    @property
    def str(self: Ref[Series]) -> _StrAccessor:
        return _StrAccessor([v for v in self.values], [v for v in self.index], self.name)

    @property
    def dt(self: Ref[Series]) -> _DtAccessor:
        return _DtAccessor([v for v in self.values], [v for v in self.index], self.name)

    def _pos(self: Ref[Series], key: PyVal) -> int:
        """Position of an index label (-1 when absent)."""
        n: int = len(self.index)
        if pyval_kind(key) == "int":
            k: int = int(key)
            if k >= 0 and k < n and self.index[k] == key:
                return k
        for i in range(n):
            if self.index[i] == key:
                return i
        return -1

    def __getitem__(self: Ref[Series], key: PyVal) -> PyVal:
        p: int = self._pos(key)
        if p < 0:
            raise KeyError(f"{key!r}")
        return _cell_out(self.values[p])

    def __setitem__(self: Mut[Series], key: PyVal, value: PyVal) -> None:
        p: int = self._pos(key)
        if p < 0:
            self.index.append(key)
            self.values.append(value)
        else:
            self.values[p] = value

    def get(self: Ref[Series], key: PyVal, default: PyVal = None) -> PyVal:
        p: int = self._pos(key)
        if p < 0:
            return default
        return _cell_out(self.values[p])

    def tolist(self: Ref[Series]) -> list[PyVal]:
        return _cells_out(self.values)

    def to_list(self: Ref[Series]) -> list[PyVal]:
        return _cells_out(self.values)

    def to_dict(self: Ref[Series]) -> PyVal:
        out: dict[str, PyVal] = {}
        for i in range(len(self.values)):
            out[str(self.index[i])] = _cell_out(self.values[i])
        return out

    def keys(self: Ref[Series]) -> list[PyVal]:
        return [v for v in self.index]

    def copy(self: Ref[Series]) -> Series:
        return Series(name=self.name, _v=[v for v in self.values],
                      _i=[v for v in self.index])

    def rename(self: Ref[Series], name: PyVal) -> Series:
        return Series(name=name, _v=[v for v in self.values], _i=[v for v in self.index])

    def head(self: Ref[Series], n: int = 5) -> Series:
        m: int = n
        if m > len(self.values):
            m = len(self.values)
        if m < 0:
            m = len(self.values) + m
            if m < 0:
                m = 0
        return Series(name=self.name, _v=[self.values[i] for i in range(m)],
                      _i=[self.index[i] for i in range(m)])

    def tail(self: Ref[Series], n: int = 5) -> Series:
        total: int = len(self.values)
        start: int = total - n
        if n < 0:
            start = -n
        if start < 0:
            start = 0
        return Series(name=self.name, _v=[self.values[i] for i in range(start, total)],
                      _i=[self.index[i] for i in range(start, total)])

    def take(self: Ref[Series], positions: Ref[list[int]]) -> Series:
        return Series(name=self.name, _v=_take(self.values, positions),
                      _i=_take(self.index, positions))

    def reset_index(self: Ref[Series], drop: bool = True) -> Series:
        return Series(name=self.name, _v=[v for v in self.values],
                      _i=_range_index(len(self.values)))

    def to_frame(self: Ref[Series], name: PyVal = None) -> DataFrame:
        col: str = "0"
        if pyval_kind(name) != "NoneType":
            col = str(name)
        elif pyval_kind(self.name) != "NoneType":
            col = str(self.name)
        cols: dict[str, list[PyVal]] = {}
        cols[col] = [v for v in self.values]
        return DataFrame(_c=move(cols), _o=[col], _i=[v for v in self.index])

    # -- element-wise helpers

    def _with(self: Ref[Series], vals: Owned[list[PyVal]]) -> Series:
        """Same index and name, new cells."""
        return Series(name=self.name, _v=move(vals), _i=[v for v in self.index])

    def _pair_name(self: Ref[Series], other: Ref[Series]) -> PyVal:
        """Result name of a two-Series operation: kept only when both names agree."""
        if self.name == other.name:
            return self.name
        return None

    def _binop(self: Ref[Series], other: Ref[int | float | str | Series], op: str) -> Series:
        """Element-wise arithmetic against a scalar or an index-aligned Series."""
        out: list[PyVal] = []
        if isinstance(other, Series):
            al: _Aligned = _align(self.index, self.values, other.index, other.values)
            for i in range(len(al.index)):
                out.append(_arith(al.left[i], al.right[i], op))
            return Series(name=self._pair_name(other), _v=move(out), _i=move(al.index))
        o: PyVal = _box_operand(other)
        for v in self.values:
            out.append(_arith(v, o, op))
        return self._with(move(out))

    def _cmpop(self: Ref[Series], other: Ref[int | float | str | Series], op: str) -> Series:
        """Element-wise comparison against a scalar or an identically-labeled Series."""
        out: list[PyVal] = []
        if isinstance(other, Series):
            if not _same_labels(self.index, other.index):
                raise ValueError("Can only compare identically-labeled Series objects")
            for i in range(len(self.values)):
                out.append(_compare(self.values[i], other.values[i], op))
            return Series(name=self._pair_name(other), _v=move(out), _i=[v for v in self.index])
        o: PyVal = _box_operand(other)
        for v in self.values:
            out.append(_compare(v, o, op))
        return self._with(move(out))

    def __add__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "+")

    def __sub__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "-")

    def __mul__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "*")

    def __truediv__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "/")

    def __floordiv__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "//")

    def __mod__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "%")

    def __pow__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "**")

    def add(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "+")

    def sub(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "-")

    def mul(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "*")

    def div(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._binop(other, "/")

    def __neg__(self: Ref[Series]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if isna(v):
                out.append(None)
            elif pyval_kind(v) == "float":
                out.append(-float(v))
            else:
                out.append(-int(_num(v)))
        return self._with(move(out))

    def __gt__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, ">")

    def __lt__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, "<")

    def __ge__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, ">=")

    def __le__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, "<=")

    def gt(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, ">")

    def lt(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, "<")

    def ge(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, ">=")

    def le(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, "<=")

    def eq(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, "==")

    def ne(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, "!=")

    def __eq__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, "==")

    def __ne__(self: Ref[Series], other: Ref[int | float | str | Series]) -> Series:
        return self._cmpop(other, "!=")

    def _rbinop(self: Ref[Series], other: Ref[int | float | str], op: str) -> Series:
        """Element-wise arithmetic with the scalar on the left (reflected operators)."""
        o: PyVal = None
        if isinstance(other, int):
            o = other
        elif isinstance(other, float):
            o = other
        elif isinstance(other, str):
            o = other
        out: list[PyVal] = []
        for v in self.values:
            out.append(_arith(o, v, op))
        return self._with(move(out))

    def __radd__(self: Ref[Series], other: Ref[int | float | str]) -> Series:
        return self._rbinop(other, "+")

    def __rsub__(self: Ref[Series], other: Ref[int | float | str]) -> Series:
        return self._rbinop(other, "-")

    def __rmul__(self: Ref[Series], other: Ref[int | float | str]) -> Series:
        return self._rbinop(other, "*")

    def __rtruediv__(self: Ref[Series], other: Ref[int | float | str]) -> Series:
        return self._rbinop(other, "/")

    def __rfloordiv__(self: Ref[Series], other: Ref[int | float | str]) -> Series:
        return self._rbinop(other, "//")

    def __rmod__(self: Ref[Series], other: Ref[int | float | str]) -> Series:
        return self._rbinop(other, "%")

    def __rpow__(self: Ref[Series], other: Ref[int | float | str]) -> Series:
        return self._rbinop(other, "**")

    def __and__(self: Ref[Series], other: Ref[Series]) -> Series:
        out: list[PyVal] = []
        for i in range(len(self.values)):
            out.append(bool(self.values[i]) and bool(other.values[i]))
        return self._with(move(out))

    def __or__(self: Ref[Series], other: Ref[Series]) -> Series:
        out: list[PyVal] = []
        for i in range(len(self.values)):
            out.append(bool(self.values[i]) or bool(other.values[i]))
        return self._with(move(out))

    def __xor__(self: Ref[Series], other: Ref[Series]) -> Series:
        out: list[PyVal] = []
        for i in range(len(self.values)):
            out.append(bool(self.values[i]) != bool(other.values[i]))
        return self._with(move(out))

    def __invert__(self: Ref[Series]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            out.append(not bool(v))
        return self._with(move(out))

    def isin(self: Ref[Series], values: PyVal) -> Series:
        keys: dict[str, bool] = {}
        for v in values:
            keys[_hkey(v)] = True
        out: list[PyVal] = []
        for c in self.values:
            out.append(_hkey(c) in keys)
        return self._with(move(out))

    def between(self: Ref[Series], left: PyVal, right: PyVal, inclusive: str = "both") -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if isna(v):
                out.append(False)
                continue
            lo: int = _cmp(v, left)
            hi: int = _cmp(v, right)
            ok_lo: bool = lo > 0 or (lo == 0 and (inclusive == "both" or inclusive == "left"))
            ok_hi: bool = hi < 0 or (hi == 0 and (inclusive == "both" or inclusive == "right"))
            out.append(ok_lo and ok_hi)
        return self._with(move(out))

    def isna(self: Ref[Series]) -> Series:
        out: list[PyVal] = [isna(v) for v in self.values]
        return self._with(move(out))

    def isnull(self: Ref[Series]) -> Series:
        out: list[PyVal] = [isna(v) for v in self.values]
        return self._with(move(out))

    def notna(self: Ref[Series]) -> Series:
        out: list[PyVal] = [notna(v) for v in self.values]
        return self._with(move(out))

    def notnull(self: Ref[Series]) -> Series:
        out: list[PyVal] = [notna(v) for v in self.values]
        return self._with(move(out))

    def fillna(self: Ref[Series], value: PyVal) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if isna(v):
                out.append(value)
            else:
                out.append(v)
        return self._with(move(out))

    def dropna(self: Ref[Series]) -> Series:
        pos: list[int] = [i for i in range(len(self.values)) if notna(self.values[i])]
        return self.take(pos)

    def astype(self: Ref[Series], dtype: str) -> Series:
        return self._with([_cast(v, dtype) for v in self.values])

    def abs(self: Ref[Series]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if isna(v):
                out.append(None)
            elif pyval_kind(v) == "float":
                out.append(abs(float(v)))
            else:
                out.append(abs(int(_num(v))))
        return self._with(move(out))

    def round(self: Ref[Series], decimals: int = 0) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "float":
                out.append(round(float(v), decimals))
            else:
                out.append(v)
        return self._with(move(out))

    def clip(self: Ref[Series], lower: PyVal = None, upper: PyVal = None) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            c: PyVal = v
            if not isna(c):
                if not isna(lower) and _cmp(c, lower) < 0:
                    c = lower
                if not isna(upper) and _cmp(c, upper) > 0:
                    c = upper
            out.append(c)
        return self._with(move(out))

    def apply(self: Ref[Series], func: Callable[[PyVal], PyVal]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            out.append(func(v))
        return self._with(move(out))

    def map(self: Ref[Series], func: Callable[[PyVal], PyVal]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            out.append(func(v))
        return self._with(move(out))

    def replace(self: Ref[Series], to_replace: PyVal, value: PyVal = None) -> Series:
        out: list[PyVal] = []
        k: str = pyval_kind(to_replace)
        for v in self.values:
            if k == "dict":
                if notna(v) and v in to_replace:
                    out.append(to_replace[v])
                else:
                    out.append(v)
            elif k == "list":
                hit: bool = False
                for t in to_replace:
                    if v == t:
                        hit = True
                if hit:
                    out.append(value)
                else:
                    out.append(v)
            elif v == to_replace:
                out.append(value)
            else:
                out.append(v)
        return self._with(move(out))

    def where(self: Ref[Series], cond: Ref[Series], other: PyVal = None) -> Series:
        out: list[PyVal] = []
        for i in range(len(self.values)):
            if bool(cond.values[i]):
                out.append(self.values[i])
            else:
                out.append(other)
        return self._with(move(out))

    def mask(self: Ref[Series], cond: Ref[Series], other: PyVal = None) -> Series:
        out: list[PyVal] = []
        for i in range(len(self.values)):
            if bool(cond.values[i]):
                out.append(other)
            else:
                out.append(self.values[i])
        return self._with(move(out))

    def shift(self: Ref[Series], periods: int = 1) -> Series:
        n: int = len(self.values)
        out: list[PyVal] = []
        for i in range(n):
            j: int = i - periods
            if j < 0 or j >= n:
                out.append(None)
            else:
                out.append(self.values[j])
        return self._with(move(out))

    def diff(self: Ref[Series], periods: int = 1) -> Series:
        n: int = len(self.values)
        out: list[PyVal] = []
        for i in range(n):
            j: int = i - periods
            if j < 0 or j >= n:
                out.append(None)
            else:
                out.append(_arith(self.values[i], self.values[j], "-"))
        return self._with(move(out))

    def cumsum(self: Ref[Series]) -> Series:
        out: list[PyVal] = []
        acc: PyVal = None
        started: bool = False
        for v in self.values:
            if isna(v):
                out.append(None)
            elif not started:
                acc = v
                started = True
                out.append(acc)
            else:
                acc = _arith(acc, v, "+")
                out.append(acc)
        return self._with(move(out))

    def cumprod(self: Ref[Series]) -> Series:
        out: list[PyVal] = []
        acc: PyVal = None
        started: bool = False
        for v in self.values:
            if isna(v):
                out.append(None)
            elif not started:
                acc = v
                started = True
                out.append(acc)
            else:
                acc = _arith(acc, v, "*")
                out.append(acc)
        return self._with(move(out))

    def _cum_extreme(self: Ref[Series], want_max: bool) -> Series:
        """Running max/min, skipping missing cells (pandas skipna=True)."""
        out: list[PyVal] = []
        acc: PyVal = None
        started: bool = False
        for v in self.values:
            if isna(v):
                out.append(None)
            elif not started:
                acc = v
                started = True
                out.append(acc)
            else:
                c: int = _cmp(v, acc)
                if (want_max and c > 0) or (not want_max and c < 0):
                    acc = v
                out.append(acc)
        return self._with(move(out))

    def cummax(self: Ref[Series]) -> Series:
        return self._cum_extreme(True)

    def cummin(self: Ref[Series]) -> Series:
        return self._cum_extreme(False)

    def pct_change(self: Ref[Series], periods: int = 1) -> Series:
        """Fractional change from the cell `periods` back; missing where undefined."""
        n: int = len(self.values)
        out: list[PyVal] = []
        for i in range(n):
            j: int = i - periods
            if j < 0 or j >= n or isna(self.values[i]) or isna(self.values[j]):
                out.append(None)
            else:
                prev: float = _num(self.values[j])
                if prev == 0.0:
                    out.append(None)
                else:
                    out.append(_num(self.values[i]) / prev - 1.0)
        return self._with(move(out))

    def rank(self: Ref[Series], method: str = "average", ascending: bool = True) -> Series:
        """pandas-style ranks as floats: average/min/max/first/dense; missing stays missing."""
        n: int = len(self.values)
        order: list[int] = []
        for i in range(n):
            if notna(self.values[i]):
                order.append(i)
        m: int = len(order)
        i2: int = 1
        while i2 < m:
            k: int = i2
            while k > 0:
                a: PyVal = self.values[order[k - 1]]
                b: PyVal = self.values[order[k]]
                c: int = _cmp(a, b)
                if not ascending:
                    c = -c
                if c > 0:
                    t: int = order[k - 1]
                    order[k - 1] = order[k]
                    order[k] = t
                    k -= 1
                else:
                    k = 0
            i2 += 1
        out: list[PyVal] = []
        for i in range(n):
            out.append(None)
        pos: int = 0
        dense: float = 0.0
        while pos < m:
            end: int = pos + 1
            while end < m and _cmp(self.values[order[pos]], self.values[order[end]]) == 0:
                end += 1
            dense += 1.0
            for q in range(pos, end):
                r: float = 0.0
                if method == "min":
                    r = float(pos + 1)
                elif method == "max":
                    r = float(end)
                elif method == "first":
                    r = float(q + 1)
                elif method == "dense":
                    r = dense
                else:
                    r = (float(pos + 1) + float(end)) / 2.0
                out[order[q]] = r
            pos = end
        return self._with(move(out))

    def rolling(self: Ref[Series], window: int, min_periods: int = -1) -> _Rolling:
        mp: int = min_periods
        if mp < 0:
            mp = window
        return _Rolling([v for v in self.values], [v for v in self.index], self.name, window, mp)

    def corr(self: Ref[Series], other: Ref[Series]) -> PyVal:
        al: _Aligned = _align(self.index, self.values, other.index, other.values)
        return _pair_stats(al.left, al.right, "corr")

    def cov(self: Ref[Series], other: Ref[Series]) -> PyVal:
        al: _Aligned = _align(self.index, self.values, other.index, other.values)
        return _pair_stats(al.left, al.right, "cov")

    # -- reductions

    def count(self: Ref[Series]) -> int:
        n: int = 0
        for v in self.values:
            if notna(v):
                n += 1
        return n

    def sum(self: Ref[Series]) -> PyVal:
        all_int: bool = True
        ti: int = 0
        tf: float = 0.0
        strs: list[str] = []
        nums: int = 0
        for v in self.values:
            if isna(v):
                continue
            if pyval_kind(v) == "str":
                strs.append(str(v))
                continue
            if not _is_num(v):
                continue
            nums += 1
            if pyval_kind(v) == "float":
                all_int = False
                tf = tf + float(v)
            else:
                iv: int = int(_num(v))
                ti = ti + iv
                tf = tf + float(iv)
        if nums == 0 and len(strs) > 0:
            return "".join(strs)
        if all_int:
            return ti
        return tf

    def prod(self: Ref[Series]) -> PyVal:
        all_int: bool = True
        pi: int = 1
        pf: float = 1.0
        for v in self.values:
            if isna(v) or not _is_num(v):
                continue
            if pyval_kind(v) == "float":
                all_int = False
                pf = pf * float(v)
            else:
                iv: int = int(_num(v))
                pi = pi * iv
                pf = pf * float(iv)
        if all_int:
            return pi
        return pf

    def mean(self: Ref[Series]) -> float:
        total: float = 0.0
        n: int = 0
        for v in self.values:
            if isna(v) or not _is_num(v):
                continue
            total = total + _num(v)
            n += 1
        if n == 0:
            raise ValueError("mean of empty Series")
        return total / n

    def var(self: Ref[Series], ddof: int = 1) -> float:
        m: float = self.mean()
        acc: float = 0.0
        n: int = 0
        for v in self.values:
            if isna(v) or not _is_num(v):
                continue
            d: float = _num(v) - m
            acc = acc + d * d
            n += 1
        if n - ddof <= 0:
            raise ValueError("variance needs more than ddof observations")
        return acc / (n - ddof)

    def std(self: Ref[Series], ddof: int = 1) -> float:
        return self.var(ddof) ** 0.5

    def median(self: Ref[Series]) -> float:
        return _quantile(_sorted_floats(self.values), 0.5)

    def quantile(self: Ref[Series], q: float = 0.5) -> float:
        return _quantile(_sorted_floats(self.values), q)

    def min(self: Ref[Series]) -> PyVal:
        best: PyVal = None
        for v in self.values:
            if isna(v):
                continue
            if isna(best) or _cmp(v, best) < 0:
                best = v
        return _cell_out(best)

    def max(self: Ref[Series]) -> PyVal:
        best: PyVal = None
        for v in self.values:
            if isna(v):
                continue
            if isna(best) or _cmp(v, best) > 0:
                best = v
        return _cell_out(best)

    def argmin(self: Ref[Series]) -> int:
        best: int = -1
        for i in range(len(self.values)):
            if isna(self.values[i]):
                continue
            if best < 0 or _cmp(self.values[i], self.values[best]) < 0:
                best = i
        return best

    def argmax(self: Ref[Series]) -> int:
        best: int = -1
        for i in range(len(self.values)):
            if isna(self.values[i]):
                continue
            if best < 0 or _cmp(self.values[i], self.values[best]) > 0:
                best = i
        return best

    def idxmin(self: Ref[Series]) -> PyVal:
        p: int = self.argmin()
        if p < 0:
            return None
        return self.index[p]

    def idxmax(self: Ref[Series]) -> PyVal:
        p: int = self.argmax()
        if p < 0:
            return None
        return self.index[p]

    def any(self: Ref[Series]) -> bool:
        for v in self.values:
            if not isna(v) and bool(v):
                return True
        return False

    def all(self: Ref[Series]) -> bool:
        for v in self.values:
            if not isna(v) and not bool(v):
                return False
        return True

    def unique(self: Ref[Series]) -> list[PyVal]:
        seen: dict[str, bool] = {}
        out: list[PyVal] = []
        for v in self.values:
            k: str = _hkey(v)
            if k not in seen:
                seen[k] = True
                out.append(v)
        return out

    def nunique(self: Ref[Series], dropna: bool = True) -> int:
        seen: dict[str, bool] = {}
        for v in self.values:
            if dropna and isna(v):
                continue
            seen[_hkey(v)] = True
        return len(seen)

    def value_counts(self: Ref[Series], ascending: bool = False, dropna: bool = True) -> Series:
        counts: dict[str, int] = {}
        firsts: list[PyVal] = []
        order: list[str] = []
        for v in self.values:
            if dropna and isna(v):
                continue
            k: str = _hkey(v)
            if k in counts:
                counts[k] += 1
            else:
                counts[k] = 1
                order.append(k)
                firsts.append(v)
        nums: list[PyVal] = []
        for k2 in order:
            nums.append(counts[k2])
        keys: list[list[PyVal]] = [move(nums)]
        pos: list[int] = _argsort(keys, [ascending], len(keys[0]))
        return Series(name="count", _v=_take(keys[0], pos), _i=_take(firsts, pos))

    def sort_values(self: Ref[Series], ascending: bool = True) -> Series:
        keys: list[list[PyVal]] = [[v for v in self.values]]
        pos: list[int] = _argsort(keys, [ascending], len(self.values))
        return self.take(pos)

    def sort_index(self: Ref[Series], ascending: bool = True) -> Series:
        keys: list[list[PyVal]] = [[v for v in self.index]]
        pos: list[int] = _argsort(keys, [ascending], len(self.values))
        return self.take(pos)

    def describe(self: Ref[Series]) -> Series:
        if _dtype_of(self.values) == "object" or _dtype_of(self.values) == "bool":
            vc: Series = self.value_counts()
            top: PyVal = None
            freq: PyVal = None
            if len(vc.values) > 0:
                top = vc.index[0]
                freq = vc.values[0]
            return Series(name=self.name, _v=[self.count(), self.nunique(), top, freq],
                          _i=["count", "unique", "top", "freq"])
        xs: list[float] = _sorted_floats(self.values)
        n: int = len(xs)
        vals: list[PyVal] = [float(n)]
        if n == 0:
            vals = [0.0, None, None, None, None, None, None, None]
        else:
            sd: PyVal = None
            if n > 1:
                sd = self.std()
            vals.append(self.mean())
            vals.append(sd)
            vals.append(xs[0])
            vals.append(_quantile(xs, 0.25))
            vals.append(_quantile(xs, 0.5))
            vals.append(_quantile(xs, 0.75))
            vals.append(xs[n - 1])
        return Series(name=self.name, _v=move(vals),
                      _i=["count", "mean", "std", "min", "25%", "50%", "75%", "max"])

    def to_json(self: Ref[Series], path: PyVal = None, orient: str = "index",
                date_format: str = "epoch", indent: int = 0) -> str:
        obj: PyVal = None
        if orient == "records" or orient == "values":
            obj = [_json_cell(v, date_format) for v in self.values]
        elif orient == "split":
            split: dict[str, PyVal] = {}
            split["name"] = self.name
            split["index"] = [_json_cell(v, date_format) for v in self.index]
            split["data"] = [_json_cell(v2, date_format) for v2 in self.values]
            obj = split
        else:
            byidx: dict[str, PyVal] = {}
            for i in range(len(self.values)):
                byidx[_json_label(self.index[i])] = _json_cell(self.values[i], date_format)
            obj = byidx
        return _emit_json(obj, path, indent)

    # -- display

    def __str__(self: Ref[Series]) -> str:
        dtype: str = _dtype_of(self.values)
        tail: str = f"dtype: {dtype}"
        n: int = len(self.values)
        if n == 0:
            if pyval_kind(self.name) != "NoneType":
                tail = f"Name: {self.name}, dtype: {dtype}"
            return f"Series([], {tail})"
        show: list[int] = _shown_rows(n)
        truncated: bool = len(show) < n
        if truncated:
            tail = f"Length: {n}, dtype: {dtype}"
        if pyval_kind(self.name) != "NoneType":
            tail = f"Name: {self.name}, {tail}"
        labels: list[str] = _labels(self.index)
        cells: list[str] = _fmt_cells(self.values, dtype)
        iw: int = _width(labels)
        vw: int = _width(cells)
        if vw < 2 and truncated:
            vw = 2
        lines: list[str] = []
        for p in show:
            if p < 0:
                lines.append(_ljust("", iw) + "    " + _rjust("..", vw))
            else:
                lines.append(_ljust(labels[p], iw) + "    " + _rjust(cells[p], vw))
        lines.append(tail)
        return "\n".join(lines)

    def __repr__(self: Ref[Series]) -> str:
        return str(self)


@dataclass
class _SeriesILoc:
    values: list[PyVal]
    index: list[PyVal]
    name: PyVal

    def __getitem__(self: Ref[_SeriesILoc], i: int) -> PyVal:
        n: int = len(self.values)
        j: int = i
        if j < 0:
            j = n + j
        if j < 0 or j >= n:
            raise IndexError("single positional indexer is out-of-bounds")
        return _cell_out(self.values[j])

    def __len__(self: Ref[_SeriesILoc]) -> int:
        return len(self.values)


@dataclass
class _SeriesLoc:
    values: list[PyVal]
    index: list[PyVal]
    name: PyVal

    def __getitem__(self: Ref[_SeriesLoc], mask: Ref[Series]) -> Series:
        if len(mask.values) != len(self.values):
            raise IndexError("Boolean index has wrong length")
        pos: list[int] = [i for i in range(len(self.values)) if bool(mask.values[i])]
        return Series(name=self.name, _v=_take(self.values, pos), _i=_take(self.index, pos))


@dataclass
class _StrAccessor:
    values: list[PyVal]
    index: list[PyVal]
    name: PyVal

    def _out(self: Ref[_StrAccessor], vals: Owned[list[PyVal]]) -> Series:
        """Wrap results with the source index and name."""
        return Series(name=self.name, _v=move(vals), _i=[v for v in self.index])

    def upper(self: Ref[_StrAccessor]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                out.append(str(v).upper())
            else:
                out.append(None)
        return self._out(move(out))

    def lower(self: Ref[_StrAccessor]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                out.append(str(v).lower())
            else:
                out.append(None)
        return self._out(move(out))

    def strip(self: Ref[_StrAccessor]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                out.append(str(v).strip())
            else:
                out.append(None)
        return self._out(move(out))

    def len(self: Ref[_StrAccessor]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                out.append(len(str(v)))
            else:
                out.append(None)
        return self._out(move(out))

    def contains(self: Ref[_StrAccessor], pat: str) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                out.append(str(v).find(pat) >= 0)
            else:
                out.append(None)
        return self._out(move(out))

    def startswith(self: Ref[_StrAccessor], pat: str) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                out.append(str(v).startswith(pat))
            else:
                out.append(None)
        return self._out(move(out))

    def endswith(self: Ref[_StrAccessor], pat: str) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                out.append(str(v).endswith(pat))
            else:
                out.append(None)
        return self._out(move(out))

    def replace(self: Ref[_StrAccessor], pat: str, repl: str) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                out.append(str(v).replace(pat, repl))
            else:
                out.append(None)
        return self._out(move(out))

    def slice(self: Ref[_StrAccessor], start: int = 0, stop: int = -1) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                s: str = str(v)
                e: int = stop
                if e < 0 or e > len(s):
                    e = len(s)
                b: int = start
                if b > e:
                    b = e
                out.append(s[b:e])
            else:
                out.append(None)
        return self._out(move(out))

    def cat(self: Ref[_StrAccessor], sep: str = "") -> str:
        parts: list[str] = []
        for v in self.values:
            if pyval_kind(v) == "str":
                parts.append(str(v))
        return sep.join(parts)


# ----------------------------------------------------------------------------- DataFrame


def _all_digits(s: str) -> bool:
    """True for a non-empty run of ASCII digits."""
    if len(s) == 0:
        return False
    for c in s:
        if c < "0" or c > "9":
            return False
    return True


def _parse_date_text(text: str, fmt: str) -> Dt:
    """Dt from date text: ISO-like forms by default, or a strftime-style format."""
    s: str = text.strip()
    if fmt != "":
        vals: dict[str, int] = {"Y": 1970, "m": 1, "d": 1, "H": 0, "M": 0, "S": 0}
        i: int = 0
        j: int = 0
        while i < len(fmt):
            c: str = fmt[i]
            if c == "%" and i + 1 < len(fmt):
                d: str = fmt[i + 1]
                width: int = 2
                if d == "Y":
                    width = 4
                seg: str = s[j:j + width]
                if not _all_digits(seg):
                    raise ValueError(f"time data '{text}' does not match format '{fmt}'")
                n: int = int(seg)
                if d == "y":
                    n = n + 2000 if n < 69 else n + 1900
                    vals["Y"] = n
                elif d in vals:
                    vals[d] = n
                else:
                    raise ValueError(f"unsupported format directive '%{d}'")
                j += width
                i += 2
            else:
                if j >= len(s) or s[j] != c:
                    raise ValueError(f"time data '{text}' does not match format '{fmt}'")
                j += 1
                i += 1
        if j != len(s):
            raise ValueError(f"time data '{text}' does not match format '{fmt}'")
        return make(vals["Y"], vals["m"], vals["d"], vals["H"], vals["M"], vals["S"])
    date_part: str = s
    time_part: str = ""
    for k in range(len(s)):
        ch: str = s[k]
        if ch == "T" or ch == " ":
            date_part = s[:k]
            time_part = s[k + 1:].strip()
            break
    segs: list[str] = date_part.replace("/", "-").replace(".", "-").split("-")
    if len(segs) != 3:
        raise ValueError(f"Unknown datetime string format, unable to parse: {text}")
    year: int = 0
    month: int = 0
    day: int = 0
    if len(segs[0]) == 4:
        year = int(segs[0])
        month = int(segs[1])
        day = int(segs[2])
    elif len(segs[2]) == 4:
        month = int(segs[0])
        day = int(segs[1])
        year = int(segs[2])
    else:
        raise ValueError(f"Unknown datetime string format, unable to parse: {text}")
    hour: int = 0
    minute: int = 0
    second: int = 0
    if time_part != "":
        tsegs: list[str] = time_part.split(":")
        if len(tsegs) < 2 or len(tsegs) > 3:
            raise ValueError(f"Unknown datetime string format, unable to parse: {text}")
        hour = int(tsegs[0])
        minute = int(tsegs[1])
        if len(tsegs) == 3:
            sec_text: str = tsegs[2]
            dot: int = sec_text.find(".")
            if dot >= 0:
                sec_text = sec_text[:dot]
            second = int(sec_text)
    return make(year, month, day, hour, minute, second)


def _to_dt_cell(v: PyVal, fmt: str, coerce: bool) -> PyVal:
    """One cell converted to a datetime cell (missing stays missing)."""
    if isna(v) or _is_dt(v):
        return v
    k: str = pyval_kind(v)
    if k == "str":
        if not coerce:
            return _dt_cell(_parse_date_text(str(v), fmt))
        try:
            d: Dt = _parse_date_text(str(v), fmt)
            return _dt_cell(d)
        except ValueError:
            return None
    if coerce:
        return None
    raise TypeError(f"<class '{k}'> is not convertible to datetime")


def to_datetime(arg: Ref[Series | list[PyVal] | str], format: str = "",
                errors: str = "raise") -> Series:
    """pandas.to_datetime over a Series, a list of date texts, or one text."""
    coerce: bool = errors == "coerce"
    if isinstance(arg, Series):
        out: list[PyVal] = []
        for v in arg.values:
            out.append(_to_dt_cell(v, format, coerce))
        return Series(name=arg.name, _v=move(out), _i=[v for v in arg.index])
    out2: list[PyVal] = []
    if isinstance(arg, list):
        for v2 in arg:
            out2.append(_to_dt_cell(v2, format, coerce))
    elif isinstance(arg, str):
        out2.append(_to_dt_cell(arg, format, coerce))
    n: int = len(out2)
    return Series(_v=move(out2), _i=_range_index(n))


def _strftime(d: Ref[Dt], fmt: str) -> str:
    """strftime subset: %Y %y %m %d %H %M %S %B %b %A %a %j %%."""
    out: str = ""
    i: int = 0
    while i < len(fmt):
        c: str = fmt[i]
        if c == "%" and i + 1 < len(fmt):
            k: str = fmt[i + 1]
            if k == "Y":
                out = out + _pad0(d.year, 4)
            elif k == "y":
                out = out + _pad0(d.year % 100, 2)
            elif k == "m":
                out = out + _pad0(d.month, 2)
            elif k == "d":
                out = out + _pad0(d.day, 2)
            elif k == "H":
                out = out + _pad0(d.hour, 2)
            elif k == "M":
                out = out + _pad0(d.minute, 2)
            elif k == "S":
                out = out + _pad0(d.second, 2)
            elif k == "B":
                out = out + _month_name(d.month)
            elif k == "b":
                out = out + _month_name(d.month)[:3]
            elif k == "A":
                out = out + _day_name(_dt_weekday(d))
            elif k == "a":
                out = out + _day_name(_dt_weekday(d))[:3]
            elif k == "j":
                out = out + _pad0(_dt_doy(d), 3)
            elif k == "%":
                out = out + "%"
            else:
                out = out + "%" + k
            i += 2
        else:
            out = out + c
            i += 1
    return out


def _pad0(n: int, width: int) -> str:
    """Zero-padded decimal text."""
    out: str = str(n)
    while len(out) < width:
        out = "0" + out
    return out


@dataclass
class _DtAccessor:
    values: list[PyVal]
    index: list[PyVal]
    name: PyVal

    def _out(self: Ref[_DtAccessor], vals: Owned[list[PyVal]]) -> Series:
        """Wrap results with the source index and name."""
        return Series(name=self.name, _v=move(vals), _i=[v for v in self.index])

    def _field(self: Ref[_DtAccessor], what: str) -> Series:
        """One integer component per cell (missing stays missing)."""
        out: list[PyVal] = []
        for v in self.values:
            if not _is_dt(v):
                out.append(None)
                continue
            d: Dt = _dt_parse(v)
            if what == "year":
                out.append(d.year)
            elif what == "month":
                out.append(d.month)
            elif what == "day":
                out.append(d.day)
            elif what == "hour":
                out.append(d.hour)
            elif what == "minute":
                out.append(d.minute)
            elif what == "second":
                out.append(d.second)
            elif what == "dayofweek":
                out.append(_dt_weekday(d))
            elif what == "dayofyear":
                out.append(_dt_doy(d))
            elif what == "quarter":
                out.append((d.month - 1) // 3 + 1)
            elif what == "days_in_month":
                out.append(_dt_dim(d.year, d.month))
        return self._out(move(out))

    @property
    def year(self: Ref[_DtAccessor]) -> Series:
        return self._field("year")

    @property
    def month(self: Ref[_DtAccessor]) -> Series:
        return self._field("month")

    @property
    def day(self: Ref[_DtAccessor]) -> Series:
        return self._field("day")

    @property
    def hour(self: Ref[_DtAccessor]) -> Series:
        return self._field("hour")

    @property
    def minute(self: Ref[_DtAccessor]) -> Series:
        return self._field("minute")

    @property
    def second(self: Ref[_DtAccessor]) -> Series:
        return self._field("second")

    @property
    def dayofweek(self: Ref[_DtAccessor]) -> Series:
        return self._field("dayofweek")

    @property
    def weekday(self: Ref[_DtAccessor]) -> Series:
        return self._field("dayofweek")

    @property
    def dayofyear(self: Ref[_DtAccessor]) -> Series:
        return self._field("dayofyear")

    @property
    def quarter(self: Ref[_DtAccessor]) -> Series:
        return self._field("quarter")

    @property
    def days_in_month(self: Ref[_DtAccessor]) -> Series:
        return self._field("days_in_month")

    @property
    def date(self: Ref[_DtAccessor]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if _is_dt(v):
                out.append(_dt_iso(v)[:10])
            else:
                out.append(None)
        return self._out(move(out))

    def day_name(self: Ref[_DtAccessor]) -> Series:
        return self.strftime("%A")

    def month_name(self: Ref[_DtAccessor]) -> Series:
        return self.strftime("%B")

    def strftime(self: Ref[_DtAccessor], fmt: str) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if _is_dt(v):
                d: Dt = _dt_parse(v)
                out.append(_strftime(d, fmt))
            else:
                out.append(None)
        return self._out(move(out))

    def normalize(self: Ref[_DtAccessor]) -> Series:
        out: list[PyVal] = []
        for v in self.values:
            if _is_dt(v):
                out.append(DT_TAG + _dt_iso(v)[:10] + "T00:00:00")
            else:
                out.append(None)
        return self._out(move(out))


@dataclass
class _Rolling:
    values: list[PyVal]
    index: list[PyVal]
    name: PyVal
    window: int
    min_periods: int

    def _agg(self: Ref[_Rolling], op: str) -> Series:
        """Trailing-window aggregate as a Series over the source index."""
        return Series(name=self.name, _v=_window_agg(self.values, self.window, self.min_periods, op),
                      _i=[v for v in self.index])

    def sum(self: Ref[_Rolling]) -> Series:
        return self._agg("sum")

    def mean(self: Ref[_Rolling]) -> Series:
        return self._agg("mean")

    def min(self: Ref[_Rolling]) -> Series:
        return self._agg("min")

    def max(self: Ref[_Rolling]) -> Series:
        return self._agg("max")

    def std(self: Ref[_Rolling]) -> Series:
        return self._agg("std")

    def var(self: Ref[_Rolling]) -> Series:
        return self._agg("var")

    def median(self: Ref[_Rolling]) -> Series:
        return self._agg("median")

    def count(self: Ref[_Rolling]) -> Series:
        return self._agg("count")


@dataclass
class _FrameRolling:
    frame: DataFrame
    window: int
    min_periods: int

    def _agg(self: Ref[_FrameRolling], op: str) -> DataFrame:
        """Trailing-window aggregate of every numeric column."""
        names: list[str] = self.frame._numeric_cols()
        cols: dict[str, list[PyVal]] = {}
        for c in names:
            cols[c] = _window_agg(self.frame._cols[c], self.window, self.min_periods, op)
        return DataFrame(_c=move(cols), _o=move(names), _i=[v for v in self.frame.index])

    def sum(self: Ref[_FrameRolling]) -> DataFrame:
        return self._agg("sum")

    def mean(self: Ref[_FrameRolling]) -> DataFrame:
        return self._agg("mean")

    def min(self: Ref[_FrameRolling]) -> DataFrame:
        return self._agg("min")

    def max(self: Ref[_FrameRolling]) -> DataFrame:
        return self._agg("max")

    def std(self: Ref[_FrameRolling]) -> DataFrame:
        return self._agg("std")

    def count(self: Ref[_FrameRolling]) -> DataFrame:
        return self._agg("count")


@dataclass
class _RowIter:
    frame: DataFrame
    i: int

    def __iter__(self: Ref[_RowIter]) -> _RowIter:
        return self

    def __next__(self: Mut[_RowIter]) -> tuple[PyVal, Series]:
        if self.i >= len(self.frame.index):
            raise StopIteration()
        j: int = self.i
        self.i += 1
        idx: list[PyVal] = []
        for c in self.frame.columns:
            idx.append(c)
        row: Series = Series(name=self.frame.index[j], _v=self.frame._row(j), _i=move(idx))
        return (self.frame.index[j], move(row))


@dataclass
class _TupleIter:
    frame: DataFrame
    i: int
    index: bool

    def __iter__(self: Ref[_TupleIter]) -> _TupleIter:
        return self

    def __next__(self: Mut[_TupleIter]) -> list[PyVal]:
        if self.i >= len(self.frame.index):
            raise StopIteration()
        j: int = self.i
        self.i += 1
        out: list[PyVal] = []
        if self.index:
            out.append(self.frame.index[j])
        for c in self.frame.columns:
            out.append(self.frame._cols[c][j])
        return out


def _col_names(data: PyVal, columns: PyVal) -> list[str]:
    """Column names for the DataFrame constructor input."""
    names: list[str] = []
    k: str = pyval_kind(data)
    if pyval_kind(columns) == "list":
        for pc in columns:
            names.append(str(pc))
        return names
    if k == "dict":
        for key in data:
            names.append(str(key))
        return names
    if k == "list":
        seen: dict[str, bool] = {}
        first: bool = True
        for row in data:
            rk: str = pyval_kind(row)
            if rk == "dict":
                for key in row:
                    ks: str = str(key)
                    if ks not in seen:
                        seen[ks] = True
                        names.append(ks)
            elif rk == "list" and first:
                for i in range(len(row)):
                    names.append(str(i))
            first = False
    return names


@dataclass
class DataFrame:
    _cols: dict[str, list[PyVal]]
    columns: list[str]
    index: list[PyVal]

    def __init__(self: Mut[DataFrame], data: PyVal = None, index: PyVal = None,
                 columns: PyVal = None,
                 _c: Owned[Optional[dict[str, list[PyVal]]]] = None,
                 _o: Owned[Optional[list[str]]] = None,
                 _i: Owned[Optional[list[PyVal]]] = None) -> None:
        cols: dict[str, list[PyVal]] = {}
        order: list[str] = []
        idx: list[PyVal] = []
        nrows: int = 0
        prebuilt: bool = _c is not None
        if _c is not None:
            cols = move(_c)
        if _o is not None:
            order = move(_o)
        if not prebuilt:
            order = _col_names(data, columns)
            k: str = pyval_kind(data)
            if k == "dict":
                given: bool = pyval_kind(index) == "list"
                for name in order:
                    if name not in data:
                        raise KeyError(f"'{name}'")
                    col: PyVal = data[name]
                    if pyval_kind(col) == "list":
                        if len(col) > nrows:
                            nrows = len(col)
                    elif given and len(index) > nrows:
                        nrows = len(index)
                    elif nrows < 1 and not given:
                        nrows = 1
                for name2 in order:
                    col2: PyVal = data[name2]
                    vals: list[PyVal] = []
                    if pyval_kind(col2) == "list":
                        if len(col2) != nrows:
                            raise ValueError("All arrays must be of the same length")
                        vals = _unbox_list(col2)
                    else:
                        for _ in range(nrows):
                            vals.append(col2)
                    cols[name2] = move(vals)
            elif k == "list":
                nrows = len(data)
                for name3 in order:
                    cols[name3] = []
                for row in data:
                    rk: str = pyval_kind(row)
                    for ci in range(len(order)):
                        name4: str = order[ci]
                        if rk == "dict":
                            if name4 in row:
                                cols[name4].append(row[name4])
                            else:
                                cols[name4].append(None)
                        elif rk == "list":
                            if ci < len(row):
                                cols[name4].append(row[ci])
                            else:
                                cols[name4].append(None)
                        else:
                            cols[name4].append(row)
            elif k != "NoneType":
                raise TypeError("DataFrame constructor not properly called!")
            for name5 in order:
                if name5 not in cols:
                    cols[name5] = []
                    for _ in range(nrows):
                        cols[name5].append(None)
        else:
            for name6 in order:
                nrows = len(cols[name6])
                break
        if _i is not None:
            idx = move(_i)
        elif pyval_kind(index) == "list":
            idx = _unbox_list(index)
            if len(idx) != nrows:
                raise ValueError(f"Length of values ({nrows}) does not match length of "
                                 f"index ({len(idx)})")
        else:
            idx = _range_index(nrows)
        self._cols = move(cols)
        self.columns = move(order)
        self.index = move(idx)

    # -- shape & access

    def __len__(self: Ref[DataFrame]) -> int:
        return len(self.index)

    @property
    def shape(self: Ref[DataFrame]) -> tuple[int, int]:
        return (len(self.index), len(self.columns))

    @property
    def size(self: Ref[DataFrame]) -> int:
        return len(self.index) * len(self.columns)

    @property
    def empty(self: Ref[DataFrame]) -> bool:
        return len(self.index) == 0 or len(self.columns) == 0

    @property
    def dtypes(self: Ref[DataFrame]) -> Series:
        out: list[PyVal] = []
        idx: list[PyVal] = []
        for c in self.columns:
            out.append(_dtype_of(self._cols[c]))
            idx.append(c)
        return Series(_v=move(out), _i=move(idx))

    @property
    def values(self: Ref[DataFrame]) -> list[list[PyVal]]:
        rows: list[list[PyVal]] = []
        for i in range(len(self.index)):
            rows.append(_cells_out(self._row(i)))
        return rows

    @property
    def iloc(self: Ref[DataFrame]) -> _ILoc:
        return _ILoc(self.copy())

    @property
    def loc(self: Ref[DataFrame]) -> _Loc:
        return _Loc(self.copy())

    def _row(self: Ref[DataFrame], i: int) -> list[PyVal]:
        """Cells of row i in column order."""
        out: list[PyVal] = []
        for c in self.columns:
            out.append(self._cols[c][i])
        return out

    def _col(self: Ref[DataFrame], name: str) -> list[PyVal]:
        """Copy of a column's cells (KeyError when absent)."""
        if name not in self._cols:
            raise KeyError(f"'{name}'")
        return [v for v in self._cols[name]]

    @overload
    def __getitem__(self: Ref[DataFrame], key: str) -> Series: ...

    @overload
    def __getitem__(self: Ref[DataFrame], key: Ref[list[str]]) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[DataFrame], key: Ref[Series]) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[DataFrame], key: Ref[slice]) -> DataFrame: ...

    def __getitem__(self: Ref[DataFrame], key: Ref[str | list[str] | Series | slice]) -> Series | DataFrame:
        if isinstance(key, str):
            return Series(name=key, _v=self._col(key), _i=[v for v in self.index])
        if isinstance(key, Series):
            return self._filter_mask(key)
        if isinstance(key, list):
            return self._select(key)
        if isinstance(key, slice):
            return self._take_rows(_slice_positions(key, len(self.index)))
        return DataFrame()

    def __setitem__(self: Mut[DataFrame], key: str,
                    value: Ref[Series | int | float | str | bool | list[PyVal]]) -> None:
        n: int = len(self.index)
        vals: list[PyVal] = []
        if isinstance(value, Series):
            if len(value.values) != n and n > 0:
                raise ValueError(f"Length of values ({len(value.values)}) does not match "
                                 f"length of index ({n})")
            vals = [v for v in value.values]
            if n == 0 and len(self.columns) == 0:
                self.index = [v for v in value.index]
        elif isinstance(value, list):
            if len(value) != n and n > 0:
                raise ValueError(f"Length of values ({len(value)}) does not match "
                                 f"length of index ({n})")
            vals = [v for v in value]
            if n == 0 and len(self.columns) == 0:
                self.index = _range_index(len(vals))
        elif isinstance(value, bool):
            for _ in range(n):
                vals.append(value)
        elif isinstance(value, int):
            for _ in range(n):
                vals.append(value)
        elif isinstance(value, float):
            for _ in range(n):
                vals.append(value)
        elif isinstance(value, str):
            for _ in range(n):
                vals.append(value)
        if key not in self._cols:
            self.columns.append(key)
        self._cols[key] = move(vals)

    def get(self: Ref[DataFrame], key: str) -> Optional[Series]:
        if key not in self._cols:
            return None
        return self[key]

    def pop(self: Mut[DataFrame], key: str) -> Series:
        s: Series = self[key]
        self._drop_col(key)
        return s

    def _drop_col(self: Mut[DataFrame], key: str) -> None:
        """Remove a column in place."""
        keep: list[str] = [c for c in self.columns if c != key]
        self.columns = move(keep)
        self._cols.pop(key)

    def insert(self: Mut[DataFrame], loc: int, column: str, value: Ref[Series | list[PyVal]]) -> None:
        if column in self._cols:
            raise ValueError(f"cannot insert {column}, already exists")
        vals: list[PyVal] = []
        if isinstance(value, Series):
            vals = [v for v in value.values]
        elif isinstance(value, list):
            vals = [v for v in value]
        if len(vals) != len(self.index):
            raise ValueError(f"Length of values ({len(vals)}) does not match length of "
                             f"index ({len(self.index)})")
        order: list[str] = []
        for i in range(len(self.columns)):
            if i == loc:
                order.append(column)
            order.append(self.columns[i])
        if loc >= len(self.columns):
            order.append(column)
        self.columns = move(order)
        self._cols[column] = move(vals)

    def copy(self: Ref[DataFrame]) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            cols[c] = [v for v in self._cols[c]]
        return DataFrame(_c=move(cols), _o=[c for c in self.columns],
                         _i=[v for v in self.index])

    def _take_rows(self: Ref[DataFrame], pos: Ref[list[int]]) -> DataFrame:
        """Rows at the given positions, all columns."""
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            cols[c] = _take(self._cols[c], pos)
        return DataFrame(_c=move(cols), _o=[c for c in self.columns],
                         _i=_take(self.index, pos))

    def take(self: Ref[DataFrame], positions: Ref[list[int]]) -> DataFrame:
        return self._take_rows(positions)

    def head(self: Ref[DataFrame], n: int = 5) -> DataFrame:
        m: int = n
        if m > len(self.index):
            m = len(self.index)
        if m < 0:
            m = len(self.index) + m
            if m < 0:
                m = 0
        return self._take_rows([i for i in range(m)])

    def tail(self: Ref[DataFrame], n: int = 5) -> DataFrame:
        total: int = len(self.index)
        start: int = total - n
        if n < 0:
            start = -n
        if start < 0:
            start = 0
        return self._take_rows([i for i in range(start, total)])

    def _filter_mask(self: Ref[DataFrame], mask: Ref[Series]) -> DataFrame:
        """Rows where the boolean Series is truthy."""
        if len(mask.values) != len(self.index):
            raise IndexError("Boolean index has wrong length")
        return self._take_rows([i for i in range(len(self.index)) if bool(mask.values[i])])

    def filter(self: Ref[DataFrame], items: PyVal) -> DataFrame:
        names: list[str] = []
        for pc in items:
            if str(pc) in self._cols:
                names.append(str(pc))
        return self._select(names)

    def _select(self: Ref[DataFrame], names: Ref[list[str]]) -> DataFrame:
        """Column subset in the given order."""
        cols: dict[str, list[PyVal]] = {}
        for c in names:
            cols[c] = self._col(c)
        return DataFrame(_c=move(cols), _o=[c for c in names], _i=[v for v in self.index])

    def select(self: Ref[DataFrame], names: PyVal) -> DataFrame:
        picked: list[str] = []
        for c in names:
            picked.append(str(c))
        return self._select(picked)

    def drop(self: Ref[DataFrame], labels: PyVal = None, axis: int = 0,
             columns: PyVal = None, index: PyVal = None) -> DataFrame:
        col_labels: PyVal = columns
        row_labels: PyVal = index
        if pyval_kind(labels) != "NoneType":
            if axis == 1:
                col_labels = labels
            else:
                row_labels = labels
        out: DataFrame = self.copy()
        if pyval_kind(col_labels) != "NoneType":
            names: list[str] = []
            if pyval_kind(col_labels) == "list":
                for pc in col_labels:
                    names.append(str(pc))
            else:
                names.append(str(col_labels))
            for name in names:
                if name not in out._cols:
                    raise KeyError(f"['{name}'] not found in axis")
                out._drop_col(name)
        if pyval_kind(row_labels) != "NoneType":
            drop_keys: dict[str, bool] = {}
            if pyval_kind(row_labels) == "list":
                for r in row_labels:
                    drop_keys[_hkey(r)] = True
            else:
                drop_keys[_hkey(row_labels)] = True
            pos: list[int] = [i for i in range(len(out.index)) if _hkey(out.index[i]) not in drop_keys]
            return out._take_rows(pos)
        return out

    def rename(self: Ref[DataFrame], columns: PyVal = None, index: PyVal = None) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        order: list[str] = []
        for c in self.columns:
            new: str = c
            if pyval_kind(columns) == "dict" and c in columns:
                new = str(columns[c])
            order.append(new)
            cols[new] = [v for v in self._cols[c]]
        idx: list[PyVal] = []
        for lbl in self.index:
            if pyval_kind(index) == "dict" and notna(lbl) and lbl in index:
                idx.append(index[lbl])
            else:
                idx.append(lbl)
        return DataFrame(_c=move(cols), _o=move(order), _i=move(idx))

    def replace(self: Ref[DataFrame], to_replace: PyVal, value: PyVal = None) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            cols[c] = self[c].replace(to_replace, value).values
        return DataFrame(_c=move(cols), _o=[c2 for c2 in self.columns],
                         _i=[v for v in self.index])

    def set_axis(self: Ref[DataFrame], labels: PyVal, axis: int = 0) -> DataFrame:
        if axis == 1:
            names: list[str] = []
            for pc in labels:
                names.append(str(pc))
            if len(names) != len(self.columns):
                raise ValueError(f"Length mismatch: Expected axis has {len(self.columns)} "
                                 f"elements, new values have {len(names)} elements")
            cols: dict[str, list[PyVal]] = {}
            for i in range(len(names)):
                cols[names[i]] = [v for v in self._cols[self.columns[i]]]
            return DataFrame(_c=move(cols), _o=move(names), _i=[v for v in self.index])
        idx: list[PyVal] = _unbox_list(labels)
        if len(idx) != len(self.index):
            raise ValueError(f"Length mismatch: Expected axis has {len(self.index)} "
                             f"elements, new values have {len(idx)} elements")
        out: DataFrame = self.copy()
        out.index = move(idx)
        return out

    def reset_index(self: Ref[DataFrame], drop: bool = False) -> DataFrame:
        out: DataFrame = self.copy()
        if not drop:
            name: str = "index"
            if name in out._cols:
                name = "level_0"
            out.insert(0, name, [v for v in self.index])
        out.index = _range_index(len(self.index))
        return out

    def set_index(self: Ref[DataFrame], keys: str, drop: bool = True) -> DataFrame:
        idx: list[PyVal] = self._col(keys)
        out: DataFrame = self.copy()
        if drop:
            out._drop_col(keys)
        out.index = move(idx)
        return out

    def astype(self: Ref[DataFrame], dtype: str) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            cols[c] = [_cast(v, dtype) for v in self._cols[c]]
        return DataFrame(_c=move(cols), _o=[c for c in self.columns],
                         _i=[v for v in self.index])

    def round(self: Ref[DataFrame], decimals: int = 0) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            cols[c] = self[c].round(decimals).values
        return DataFrame(_c=move(cols), _o=[c for c in self.columns],
                         _i=[v for v in self.index])

    # -- missing data

    def isna(self: Ref[DataFrame]) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            flags: list[PyVal] = [isna(v) for v in self._cols[c]]
            cols[c] = move(flags)
        return DataFrame(_c=move(cols), _o=[c for c in self.columns],
                         _i=[v for v in self.index])

    def isnull(self: Ref[DataFrame]) -> DataFrame:
        return self.isna()

    def notna(self: Ref[DataFrame]) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            flags: list[PyVal] = [notna(v) for v in self._cols[c]]
            cols[c] = move(flags)
        return DataFrame(_c=move(cols), _o=[c for c in self.columns],
                         _i=[v for v in self.index])

    def fillna(self: Ref[DataFrame], value: PyVal) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            fill: PyVal = value
            if pyval_kind(value) == "dict":
                if c in value:
                    fill = value[c]
                else:
                    fill = None
            out: list[PyVal] = []
            for v in self._cols[c]:
                if isna(v) and not isna(fill):
                    out.append(fill)
                else:
                    out.append(v)
            cols[c] = move(out)
        return DataFrame(_c=move(cols), _o=[c for c in self.columns],
                         _i=[v for v in self.index])

    def dropna(self: Ref[DataFrame], how: str = "any", subset: PyVal = None) -> DataFrame:
        names: list[str] = [c for c in self.columns]
        if pyval_kind(subset) == "list":
            names = []
            for pc in subset:
                names.append(str(pc))
        pos: list[int] = []
        for i in range(len(self.index)):
            missing: int = 0
            for c in names:
                if isna(self._cols[c][i]):
                    missing += 1
            if how == "all":
                if missing < len(names) or len(names) == 0:
                    pos.append(i)
            elif missing == 0:
                pos.append(i)
        return self._take_rows(pos)

    def duplicated(self: Ref[DataFrame], subset: PyVal = None, keep: str = "first") -> Series:
        names: list[str] = [c for c in self.columns]
        if pyval_kind(subset) == "list":
            names = []
            for pc in subset:
                names.append(str(pc))
        keycols: list[list[PyVal]] = []
        for c in names:
            keycols.append([v for v in self._cols[c]])
        n: int = len(self.index)
        keys: list[str] = []
        counts: dict[str, int] = {}
        for i in range(n):
            k: str = _row_key(keycols, i)
            keys.append(k)
            if k in counts:
                counts[k] += 1
            else:
                counts[k] = 1
        seen: dict[str, int] = {}
        out: list[PyVal] = []
        for i2 in range(n):
            k2: str = keys[i2]
            prior: int = 0
            if k2 in seen:
                prior = seen[k2]
            seen[k2] = prior + 1
            if keep == "first":
                out.append(prior > 0)
            elif keep == "last":
                out.append(prior + 1 < counts[k2])
            else:
                out.append(counts[k2] > 1)
        return Series(_v=move(out), _i=[v for v in self.index])

    def drop_duplicates(self: Ref[DataFrame], subset: PyVal = None, keep: str = "first") -> DataFrame:
        dup: Series = self.duplicated(subset, keep)
        return self._take_rows([i for i in range(len(self.index)) if not bool(dup.values[i])])

    # -- ordering

    def sort_values(self: Ref[DataFrame], by: PyVal, ascending: PyVal = True) -> DataFrame:
        names: list[str] = []
        if pyval_kind(by) == "list":
            for pc in by:
                names.append(str(pc))
        else:
            names.append(str(by))
        asc: list[bool] = []
        for i in range(len(names)):
            if pyval_kind(ascending) == "list":
                asc.append(bool(ascending[i]))
            else:
                asc.append(bool(ascending))
        keys: list[list[PyVal]] = []
        for c in names:
            keys.append(self._col(c))
        pos: list[int] = _argsort(keys, asc, len(self.index))
        return self._take_rows(pos)

    def sort_index(self: Ref[DataFrame], ascending: bool = True) -> DataFrame:
        keys: list[list[PyVal]] = [[v for v in self.index]]
        pos: list[int] = _argsort(keys, [ascending], len(self.index))
        return self._take_rows(pos)

    def nlargest(self: Ref[DataFrame], n: int, columns: PyVal) -> DataFrame:
        return self.sort_values(columns, False).head(n)

    def nsmallest(self: Ref[DataFrame], n: int, columns: PyVal) -> DataFrame:
        return self.sort_values(columns, True).head(n)

    # -- reductions (numeric columns only)

    def _numeric_cols(self: Ref[DataFrame]) -> list[str]:
        """Columns whose dtype is numeric or bool."""
        out: list[str] = []
        for c in self.columns:
            d: str = _dtype_of(self._cols[c])
            if d == "int64" or d == "float64" or d == "bool":
                out.append(c)
        return out

    def _reduce(self: Ref[DataFrame], op: str) -> Series:
        """Per-column reduction producing a Series indexed by column name."""
        names: list[str] = self._numeric_cols()
        if op == "count" or op == "nunique":
            names = [c for c in self.columns]
        out: list[PyVal] = []
        idx: list[PyVal] = []
        for c in names:
            s: Series = self[c]
            if op == "sum":
                out.append(s.sum())
            elif op == "mean":
                out.append(s.mean())
            elif op == "min":
                out.append(s.min())
            elif op == "max":
                out.append(s.max())
            elif op == "count":
                out.append(s.count())
            elif op == "nunique":
                out.append(s.nunique())
            elif op == "median":
                out.append(s.median())
            elif op == "std":
                out.append(s.std())
            elif op == "var":
                out.append(s.var())
            elif op == "prod":
                out.append(s.prod())
            idx.append(c)
        return Series(_v=move(out), _i=move(idx))

    def sum(self: Ref[DataFrame]) -> Series:
        return self._reduce("sum")

    def mean(self: Ref[DataFrame]) -> Series:
        return self._reduce("mean")

    def min(self: Ref[DataFrame]) -> Series:
        return self._reduce("min")

    def max(self: Ref[DataFrame]) -> Series:
        return self._reduce("max")

    def count(self: Ref[DataFrame]) -> Series:
        return self._reduce("count")

    def nunique(self: Ref[DataFrame]) -> Series:
        return self._reduce("nunique")

    def median(self: Ref[DataFrame]) -> Series:
        return self._reduce("median")

    def std(self: Ref[DataFrame]) -> Series:
        return self._reduce("std")

    def var(self: Ref[DataFrame]) -> Series:
        return self._reduce("var")

    def prod(self: Ref[DataFrame]) -> Series:
        return self._reduce("prod")

    def describe(self: Ref[DataFrame]) -> DataFrame:
        names: list[str] = self._numeric_cols()
        cols: dict[str, list[PyVal]] = {}
        for c in names:
            cols[c] = self[c].describe().values
        return DataFrame(_c=move(cols), _o=move(names),
                         _i=["count", "mean", "std", "min", "25%", "50%", "75%", "max"])

    def apply(self: Ref[DataFrame], func: Callable[[Series], PyVal], axis: int = 0) -> Series:
        out: list[PyVal] = []
        idx: list[PyVal] = []
        if axis == 1:
            for i in range(len(self.index)):
                row: Series = self.iloc[i]
                out.append(func(move(row)))
                idx.append(self.index[i])
        else:
            for c in self.columns:
                col: Series = self[c]
                out.append(func(move(col)))
                idx.append(c)
        return Series(_v=move(out), _i=move(idx))

    def applymap(self: Ref[DataFrame], func: Callable[[PyVal], PyVal]) -> DataFrame:
        cols: dict[str, list[PyVal]] = {}
        for c in self.columns:
            out: list[PyVal] = []
            for v in self._cols[c]:
                out.append(func(v))
            cols[c] = move(out)
        return DataFrame(_c=move(cols), _o=[c for c in self.columns],
                         _i=[v for v in self.index])

    def map(self: Ref[DataFrame], func: Callable[[PyVal], PyVal]) -> DataFrame:
        return self.applymap(func)

    # -- windows, correlation, iteration

    def rolling(self: Ref[DataFrame], window: int, min_periods: int = -1) -> _FrameRolling:
        mp: int = min_periods
        if mp < 0:
            mp = window
        return _FrameRolling(self.copy(), window, mp)

    def _pairwise(self: Ref[DataFrame], op: str) -> DataFrame:
        """Square frame of pairwise statistics over the numeric columns."""
        names: list[str] = self._numeric_cols()
        cols: dict[str, list[PyVal]] = {}
        idx: list[PyVal] = []
        for c in names:
            idx.append(c)
        for c2 in names:
            vals: list[PyVal] = []
            for r in names:
                if op == "corr" and r == c2:
                    vals.append(1.0)
                else:
                    vals.append(_pair_stats(self._cols[r], self._cols[c2], op))
            cols[c2] = move(vals)
        return DataFrame(_c=move(cols), _o=move(names), _i=move(idx))

    def corr(self: Ref[DataFrame]) -> DataFrame:
        return self._pairwise("corr")

    def cov(self: Ref[DataFrame]) -> DataFrame:
        return self._pairwise("cov")

    def iterrows(self: Ref[DataFrame]) -> _RowIter:
        return _RowIter(self.copy(), 0)

    def itertuples(self: Ref[DataFrame], index: bool = True) -> _TupleIter:
        return _TupleIter(self.copy(), 0, index)

    # -- reshaping

    def pivot_table(self: Ref[DataFrame], values: PyVal = None, index: PyVal = None,
                    columns: PyVal = None, aggfunc: str = "mean",
                    fill_value: PyVal = None) -> DataFrame:
        return _pivot(self, values, index, columns, aggfunc, fill_value, False)

    def pivot(self: Ref[DataFrame], index: PyVal = None, columns: PyVal = None,
              values: PyVal = None) -> DataFrame:
        return _pivot(self, values, index, columns, "first", None, True)

    def melt(self: Ref[DataFrame], id_vars: PyVal = None, value_vars: PyVal = None,
             var_name: str = "variable", value_name: str = "value") -> DataFrame:
        ids: list[str] = _list_of_names(id_vars)
        vars_: list[str] = _list_of_names(value_vars)
        if len(vars_) == 0:
            for c in self.columns:
                if c not in ids:
                    vars_.append(c)
        cols: dict[str, list[PyVal]] = {}
        order: list[str] = []
        for idc in ids:
            if idc not in self._cols:
                raise KeyError(f"'{idc}'")
            cols[idc] = []
            order.append(idc)
        cols[var_name] = []
        cols[value_name] = []
        order.append(var_name)
        order.append(value_name)
        n: int = len(self.index)
        for v in vars_:
            if v not in self._cols:
                raise KeyError(f"'{v}'")
            for i in range(n):
                for idc2 in ids:
                    cols[idc2].append(self._cols[idc2][i])
                cols[var_name].append(v)
                cols[value_name].append(self._cols[v][i])
        total: int = n * len(vars_)
        return DataFrame(_c=move(cols), _o=move(order), _i=_range_index(total))

    def query(self: Ref[DataFrame], expr: str) -> DataFrame:
        mask: list[PyVal] = _eval_expr(self, expr)
        pos: list[int] = [i for i in range(len(mask)) if bool(mask[i])]
        return self._take_rows(pos)

    def eval(self: Ref[DataFrame], expr: str) -> Series:
        return Series(_v=_eval_expr(self, expr), _i=[v for v in self.index])

    def to_json(self: Ref[DataFrame], path: PyVal = None, orient: str = "columns",
                date_format: str = "epoch", indent: int = 0) -> str:
        obj: PyVal = None
        if orient == "records":
            recs: list[PyVal] = []
            for i in range(len(self.index)):
                rec: dict[str, PyVal] = {}
                for c in self.columns:
                    rec[c] = _json_cell(self._cols[c][i], date_format)
                recs.append(rec)
            obj = recs
        elif orient == "index":
            byrow: dict[str, PyVal] = {}
            for i2 in range(len(self.index)):
                rec2: dict[str, PyVal] = {}
                for c2 in self.columns:
                    rec2[c2] = _json_cell(self._cols[c2][i2], date_format)
                byrow[_json_label(self.index[i2])] = rec2
            obj = byrow
        elif orient == "split":
            split: dict[str, PyVal] = {}
            split["columns"] = [c3 for c3 in self.columns]
            split["index"] = [_json_cell(v, date_format) for v in self.index]
            rows: list[PyVal] = []
            for i3 in range(len(self.index)):
                rows.append([_json_cell(self._cols[c4][i3], date_format) for c4 in self.columns])
            split["data"] = rows
            obj = split
        elif orient == "values":
            rows2: list[PyVal] = []
            for i4 in range(len(self.index)):
                rows2.append([_json_cell(self._cols[c5][i4], date_format) for c5 in self.columns])
            obj = rows2
        else:
            bycol: dict[str, PyVal] = {}
            for c6 in self.columns:
                col: dict[str, PyVal] = {}
                for i5 in range(len(self.index)):
                    col[_json_label(self.index[i5])] = _json_cell(self._cols[c6][i5], date_format)
                bycol[c6] = col
            obj = bycol
        return _emit_json(obj, path, indent)

    # -- grouping & joining

    def groupby(self: Ref[DataFrame], by: PyVal, sort: bool = True) -> DataFrameGroupBy:
        keys: list[str] = []
        if pyval_kind(by) == "list":
            for pc in by:
                keys.append(str(pc))
        else:
            keys.append(str(by))
        keycols: list[list[PyVal]] = []
        for c in keys:
            keycols.append(self._col(c))
        n: int = len(self.index)
        gid: dict[str, int] = {}
        groups: list[list[int]] = []
        firsts: list[int] = []
        for i in range(n):
            skip: bool = False
            for kc in keycols:
                if isna(kc[i]):
                    skip = True
            if skip:
                continue
            k: str = _row_key(keycols, i)
            if k in gid:
                groups[gid[k]].append(i)
            else:
                gid[k] = len(groups)
                groups.append([i])
                firsts.append(i)
        order: list[int] = []
        for g in range(len(groups)):
            order.append(g)
        if sort:
            gkeys: list[list[PyVal]] = []
            for kc2 in keycols:
                gkeys.append(_take(kc2, firsts))
            asc: list[bool] = []
            for _ in keys:
                asc.append(True)
            order = _argsort(gkeys, asc, len(groups))
        sorted_groups: list[list[int]] = []
        key_rows: list[list[PyVal]] = []
        for g2 in order:
            sorted_groups.append([p for p in groups[g2]])
            key_rows.append([kc3[firsts[g2]] for kc3 in keycols])
        value_cols: list[str] = []
        for c in self.columns:
            if c not in keys:
                value_cols.append(c)
        return DataFrameGroupBy(self.copy(), move(keys), move(sorted_groups), move(key_rows),
                                move(value_cols))

    def merge(self: Ref[DataFrame], right: Ref[DataFrame], on: PyVal = None,
              how: str = "inner", left_on: PyVal = None, right_on: PyVal = None,
              suffixes: PyVal = None) -> DataFrame:
        return merge(self, right, on, how, left_on, right_on, suffixes)

    def equals(self: Ref[DataFrame], other: Ref[DataFrame]) -> bool:
        if len(self.columns) != len(other.columns) or len(self.index) != len(other.index):
            return False
        for i in range(len(self.columns)):
            if self.columns[i] != other.columns[i]:
                return False
        for j in range(len(self.index)):
            if self.index[j] != other.index[j]:
                return False
        for c in self.columns:
            n: int = len(self._cols[c])
            for k in range(n):
                av: PyVal = self._cols[c][k]
                bv: PyVal = other._cols[c][k]
                if av != bv and not (isna(av) and isna(bv)):
                    return False
        return True

    # -- export

    def to_dict(self: Ref[DataFrame], orient: str = "dict") -> PyVal:
        if orient == "records":
            recs: list[PyVal] = []
            for i in range(len(self.index)):
                rec: dict[str, PyVal] = {}
                for c in self.columns:
                    rec[c] = self._cols[c][i]
                recs.append(rec)
            return recs
        if orient == "list":
            lists: dict[str, PyVal] = {}
            for c in self.columns:
                lists[c] = [v for v in self._cols[c]]
            return lists
        if orient == "index":
            byrow: dict[str, PyVal] = {}
            for i in range(len(self.index)):
                rec2: dict[str, PyVal] = {}
                for c in self.columns:
                    rec2[c] = self._cols[c][i]
                byrow[str(self.index[i])] = rec2
            return byrow
        out: dict[str, PyVal] = {}
        for c in self.columns:
            col: dict[str, PyVal] = {}
            for i in range(len(self.index)):
                col[str(self.index[i])] = self._cols[c][i]
            out[c] = col
        return out

    def to_records(self: Ref[DataFrame]) -> list[PyVal]:
        recs: list[PyVal] = []
        for i in range(len(self.index)):
            rec: dict[str, PyVal] = {}
            for c in self.columns:
                rec[c] = self._cols[c][i]
            recs.append(rec)
        return recs

    def to_csv(self: Ref[DataFrame], path: PyVal = None, sep: str = ",",
               index: bool = True, header: bool = True) -> str:
        lines: list[str] = []
        if header:
            cells: list[str] = []
            if index:
                cells.append("")
            for c in self.columns:
                cells.append(_csv_quote(c, sep))
            lines.append(sep.join(cells))
        for i in range(len(self.index)):
            row: list[str] = []
            if index:
                row.append(_csv_quote(_csv_cell(self.index[i]), sep))
            for c in self.columns:
                row.append(_csv_quote(_csv_cell(self._cols[c][i]), sep))
            lines.append(sep.join(row))
        text: str = "\n".join(lines) + "\n"
        if pyval_kind(path) == "str":
            with open(str(path), "w") as f:
                f.write(text)
        return text

    # -- display

    def __str__(self: Ref[DataFrame]) -> str:
        if len(self.index) == 0 or len(self.columns) == 0:
            return ("Empty DataFrame\nColumns: [" + ", ".join(self.columns) + "]\nIndex: ["
                    + ", ".join(_labels(self.index)) + "]")
        nrows: int = len(self.index)
        ncols: int = len(self.columns)
        rows: list[int] = _shown_rows(nrows)
        colpos: list[int] = _shown_cols(ncols)
        truncated: bool = len(rows) < nrows or len(colpos) < ncols
        labels: list[str] = _labels(self.index)
        iw: int = _width(labels)
        if iw < 2 and len(rows) < nrows:
            iw = 2
        header: str = _ljust("", iw)
        body: list[str] = []
        for p in rows:
            if p < 0:
                body.append(_ljust("..", iw))
            else:
                body.append(_ljust(labels[p], iw))
        for cp in colpos:
            if cp < 0:
                header = header + "  ..."
                for r in range(len(rows)):
                    body[r] = body[r] + "  ..."
                continue
            c: str = self.columns[cp]
            cells: list[str] = _fmt_cells(self._cols[c], _dtype_of(self._cols[c]))
            w: int = _width(cells)
            if len(c) > w:
                w = len(c)
            if w < 2 and len(rows) < nrows:
                w = 2
            header = header + "  " + _rjust(c, w)
            for r2 in range(len(rows)):
                if rows[r2] < 0:
                    body[r2] = body[r2] + "  " + _rjust("..", w)
                else:
                    body[r2] = body[r2] + "  " + _rjust(cells[rows[r2]], w)
        lines: list[str] = [header]
        for line in body:
            lines.append(line)
        if truncated:
            lines.append("")
            lines.append(f"[{nrows} rows x {ncols} columns]")
        return "\n".join(lines)

    def __repr__(self: Ref[DataFrame]) -> str:
        return str(self)


def _slice_positions(sl: Ref[slice], n: int) -> list[int]:
    """Row positions selected by a Python slice over n rows."""
    step: int = 1
    if pyval_kind(sl.step) != "NoneType":
        step = int(sl.step)
    if step == 0:
        raise ValueError("slice step cannot be zero")
    lo: int = 0
    hi: int = n
    if step < 0:
        lo = n - 1
        hi = -1
    if pyval_kind(sl.start) != "NoneType":
        lo = int(sl.start)
        if lo < 0:
            lo = n + lo
        if lo < 0:
            lo = 0 if step > 0 else -1
        if lo > n - 1 and step < 0:
            lo = n - 1
    if pyval_kind(sl.stop) != "NoneType":
        hi = int(sl.stop)
        if hi < 0:
            hi = n + hi
        if hi < 0:
            hi = 0 if step > 0 else -1
    if hi > n:
        hi = n
    if lo > n:
        lo = n
    out: list[int] = []
    i: int = lo
    if step > 0:
        while i < hi:
            out.append(i)
            i += step
    else:
        while i > hi:
            out.append(i)
            i += step
    return out


def _col_names_of(frame: Ref[DataFrame], col: PyVal) -> list[str]:
    """Column names selected by a str / list-of-str column key (KeyError when absent)."""
    names: list[str] = _list_of_names(col)
    for c in names:
        if c not in frame._cols:
            raise KeyError(f"'{c}'")
    return names


def _pos_cols_of(frame: Ref[DataFrame], col: PyVal) -> list[str]:
    """Column names selected by an int / list-of-int positional column key."""
    names: list[str] = []
    n: int = len(frame.columns)
    if pyval_kind(col) == "list":
        for p in col:
            q: int = int(p)
            if q < 0:
                q = n + q
            if q < 0 or q >= n:
                raise IndexError("positional indexers are out-of-bounds")
            names.append(frame.columns[q])
    else:
        q2: int = int(col)
        if q2 < 0:
            q2 = n + q2
        if q2 < 0 or q2 >= n:
            raise IndexError("single positional indexer is out-of-bounds")
        names.append(frame.columns[q2])
    return names


def _rows_cols(frame: Ref[DataFrame], pos: Ref[list[int]], names: Ref[list[str]],
               single: bool) -> Series | DataFrame:
    """Sub-frame of the given row positions and columns; one column as a Series."""
    if single:
        c: str = names[0]
        return Series(name=c, _v=_take(frame._cols[c], pos), _i=_take(frame.index, pos))
    cols: dict[str, list[PyVal]] = {}
    for c2 in names:
        cols[c2] = _take(frame._cols[c2], pos)
    return DataFrame(_c=move(cols), _o=[c3 for c3 in names], _i=_take(frame.index, pos))


@dataclass
class _ILoc:
    frame: DataFrame

    def _row(self: Ref[_ILoc], i: int) -> Series:
        """Row i (negative from the end) as a Series indexed by column name."""
        n: int = len(self.frame.index)
        j: int = i
        if j < 0:
            j = n + j
        if j < 0 or j >= n:
            raise IndexError("single positional indexer is out-of-bounds")
        idx: list[PyVal] = []
        for c in self.frame.columns:
            idx.append(c)
        return Series(name=self.frame.index[j], _v=self.frame._row(j), _i=move(idx))

    def _positions(self: Ref[_ILoc], key: Ref[int | list[int] | slice | Series]) -> list[int]:
        """Row positions selected by a positional row key."""
        n: int = len(self.frame.index)
        pos: list[int] = []
        if isinstance(key, int):
            q0: int = key
            if q0 < 0:
                q0 = n + q0
            if q0 < 0 or q0 >= n:
                raise IndexError("single positional indexer is out-of-bounds")
            pos.append(q0)
        elif isinstance(key, list):
            for p in key:
                q: int = p
                if q < 0:
                    q = n + q
                if q < 0 or q >= n:
                    raise IndexError("positional indexers are out-of-bounds")
                pos.append(q)
        elif isinstance(key, slice):
            pos = _slice_positions(key, n)
        elif isinstance(key, Series):
            if len(key.values) != n:
                raise IndexError("Boolean index has wrong length")
            for i in range(n):
                if bool(key.values[i]):
                    pos.append(i)
        return pos

    @overload
    def __getitem__(self: Ref[_ILoc], key: int) -> Series: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[list[int]]) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[slice]) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[Series]) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[list[int]], col: int) -> Series: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[list[int]], col: PyVal) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[slice], col: int) -> Series: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[slice], col: PyVal) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[Series], col: int) -> Series: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: Ref[Series], col: PyVal) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: int, col: int) -> Series: ...

    @overload
    def __getitem__(self: Ref[_ILoc], key: int, col: PyVal) -> Series: ...

    def __getitem__(self: Ref[_ILoc], key: Ref[int | list[int] | slice | Series],
                    col: PyVal = None) -> Series | DataFrame:
        if pyval_kind(col) == "NoneType":
            if isinstance(key, int):
                return self._row(key)
            return self.frame._take_rows(self._positions(key))
        names: list[str] = _pos_cols_of(self.frame, col)
        pos: list[int] = self._positions(key)
        if isinstance(key, int):
            row: Series = self._row(key)
            keep: list[PyVal] = []
            for c in names:
                keep.append(c)
            return Series(name=row.name, _v=[row[c2] for c2 in names], _i=move(keep))
        return _rows_cols(self.frame, pos, names, pyval_kind(col) == "int")

    def __len__(self: Ref[_ILoc]) -> int:
        return len(self.frame.index)


@dataclass
class _Loc:
    frame: DataFrame

    def _label_row(self: Ref[_Loc], label: PyVal) -> Series:
        """Row with the given index label as a Series (KeyError when absent)."""
        for i in range(len(self.frame.index)):
            if self.frame.index[i] == label:
                idx: list[PyVal] = []
                for c in self.frame.columns:
                    idx.append(c)
                return Series(name=label, _v=self.frame._row(i), _i=move(idx))
        raise KeyError(f"{label!r}")

    def _label_pos(self: Ref[_Loc], label: PyVal) -> int:
        """Position of an index label (KeyError when absent)."""
        for i in range(len(self.frame.index)):
            if self.frame.index[i] == label:
                return i
        raise KeyError(f"{label!r}")

    def _positions(self: Ref[_Loc], key: Ref[int | str | slice | Series]) -> list[int]:
        """Row positions selected by a label key (label slices are inclusive)."""
        n: int = len(self.frame.index)
        pos: list[int] = []
        if isinstance(key, Series):
            if len(key.values) != n:
                raise IndexError("Boolean index has wrong length")
            for i in range(n):
                if bool(key.values[i]):
                    pos.append(i)
        elif isinstance(key, slice):
            lo: int = 0
            hi: int = n - 1
            if pyval_kind(key.start) != "NoneType":
                lo = self._label_pos(key.start)
            if pyval_kind(key.stop) != "NoneType":
                hi = self._label_pos(key.stop)
            for i2 in range(lo, hi + 1):
                pos.append(i2)
        elif isinstance(key, int):
            pos.append(self._label_pos(key))
        elif isinstance(key, str):
            for i3 in range(n):
                if self.frame.index[i3] == key:
                    pos.append(i3)
            if len(pos) == 0:
                raise KeyError(f"{key!r}")
        return pos

    @overload
    def __getitem__(self: Ref[_Loc], key: Ref[Series]) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: int) -> Series: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: str) -> Series: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: Ref[slice]) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: Ref[Series], col: str) -> Series: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: Ref[Series], col: PyVal) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: Ref[slice], col: str) -> Series: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: Ref[slice], col: PyVal) -> DataFrame: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: int, col: PyVal) -> Series: ...

    @overload
    def __getitem__(self: Ref[_Loc], key: str, col: PyVal) -> Series: ...

    def __getitem__(self: Ref[_Loc], key: Ref[int | str | slice | Series],
                    col: PyVal = None) -> Series | DataFrame:
        if pyval_kind(col) == "NoneType":
            if isinstance(key, Series):
                return self.frame._filter_mask(key)
            if isinstance(key, int):
                return self._label_row(key)
            if isinstance(key, str):
                return self._label_row(key)
            if isinstance(key, slice):
                return self.frame._take_rows(self._positions(key))
            return DataFrame()
        names: list[str] = _col_names_of(self.frame, col)
        pos: list[int] = self._positions(key)
        single_row: bool = isinstance(key, int) or isinstance(key, str)
        if single_row and len(pos) > 1 and pyval_kind(col) == "str":
            return _rows_cols(self.frame, pos, names, True)
        if single_row:
            lbl: PyVal = self.frame.index[pos[0]]
            keep: list[PyVal] = []
            for c in names:
                keep.append(c)
            return Series(name=lbl, _v=[self.frame._cols[c2][pos[0]] for c2 in names],
                          _i=move(keep))
        return _rows_cols(self.frame, pos, names, pyval_kind(col) == "str")


# ----------------------------------------------------------------------------- groupby


def _agg_cells(vals: Ref[list[PyVal]], op: str) -> PyVal:
    """One aggregation over a group's cells."""
    s: Series = Series(_v=[v for v in vals])
    if op == "sum":
        return s.sum()
    if op == "mean":
        return s.mean()
    if op == "min":
        return s.min()
    if op == "max":
        return s.max()
    if op == "count":
        return s.count()
    if op == "size":
        return len(vals)
    if op == "median":
        return s.median()
    if op == "std":
        return s.std()
    if op == "var":
        return s.var()
    if op == "prod":
        return s.prod()
    if op == "nunique":
        return s.nunique()
    if op == "first":
        for v in vals:
            if notna(v):
                return v
        return None
    if op == "last":
        i: int = len(vals) - 1
        while i >= 0:
            if notna(vals[i]):
                return vals[i]
            i -= 1
        return None
    raise ValueError(f"unsupported aggregation '{op}'")


@dataclass
class DataFrameGroupBy:
    frame: DataFrame
    keys: list[str]
    groups: list[list[int]]
    key_rows: list[list[PyVal]]
    value_cols: list[str]

    @property
    def ngroups(self: Ref[DataFrameGroupBy]) -> int:
        return len(self.groups)

    def __getitem__(self: Ref[DataFrameGroupBy], key: str) -> SeriesGroupBy:
        if key not in self.frame._cols:
            raise KeyError(f"'{key}'")
        return SeriesGroupBy(self.frame.copy(), [k for k in self.keys],
                             [[p for p in g] for g in self.groups],
                             [[v for v in r] for r in self.key_rows], key)

    def _labels(self: Ref[DataFrameGroupBy]) -> list[PyVal]:
        """Group labels: the key value (one key) or a list of key values."""
        out: list[PyVal] = []
        for r in self.key_rows:
            if len(self.keys) == 1:
                out.append(r[0])
            else:
                lst: list[PyVal] = [v for v in r]
                out.append(lst)
        return out

    def _agg_frame(self: Ref[DataFrameGroupBy], ops: Ref[list[str]], cols: Ref[list[str]],
                   names: Ref[list[str]]) -> DataFrame:
        """Aggregate each (column, op) pair into a new column named names[i]."""
        out: dict[str, list[PyVal]] = {}
        order: list[str] = []
        idx: list[PyVal] = self._labels()
        if len(self.keys) > 1:
            for k in range(len(self.keys)):
                kname: str = self.keys[k]
                order.append(kname)
                out[kname] = [r[k] for r in self.key_rows]
            idx = _range_index(len(self.groups))
        for j in range(len(cols)):
            c: str = cols[j]
            vals: list[PyVal] = []
            for g in self.groups:
                vals.append(_agg_cells(_take(self.frame._cols[c], g), ops[j]))
            order.append(names[j])
            out[names[j]] = move(vals)
        return DataFrame(_c=move(out), _o=move(order), _i=move(idx))

    def _numeric_value_cols(self: Ref[DataFrameGroupBy], op: str) -> list[str]:
        """Value columns an aggregation applies to."""
        if op == "count" or op == "size" or op == "first" or op == "last" \
                or op == "nunique" or op == "min" or op == "max":
            return [c for c in self.value_cols]
        out: list[str] = []
        for c in self.value_cols:
            d: str = _dtype_of(self.frame._cols[c])
            if d == "int64" or d == "float64" or d == "bool":
                out.append(c)
            elif op == "sum" and d == "object":
                out.append(c)
        return out

    def _do(self: Ref[DataFrameGroupBy], op: str) -> DataFrame:
        """Apply one aggregation to every value column."""
        cols: list[str] = self._numeric_value_cols(op)
        ops: list[str] = []
        for _ in cols:
            ops.append(op)
        return self._agg_frame(ops, cols, cols)

    def sum(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("sum")

    def mean(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("mean")

    def min(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("min")

    def max(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("max")

    def count(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("count")

    def median(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("median")

    def std(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("std")

    def var(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("var")

    def first(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("first")

    def last(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("last")

    def nunique(self: Ref[DataFrameGroupBy]) -> DataFrame:
        return self._do("nunique")

    def size(self: Ref[DataFrameGroupBy]) -> Series:
        vals: list[PyVal] = []
        for g in self.groups:
            vals.append(len(g))
        return Series(_v=move(vals), _i=self._labels())

    def agg(self: Ref[DataFrameGroupBy], spec: PyVal) -> DataFrame:
        cols: list[str] = []
        ops: list[str] = []
        names: list[str] = []
        k: str = pyval_kind(spec)
        if k == "str":
            for c in self._numeric_value_cols(str(spec)):
                cols.append(c)
                ops.append(str(spec))
                names.append(c)
        elif k == "list":
            for c in self.value_cols:
                for op in spec:
                    cols.append(c)
                    ops.append(str(op))
                    names.append(c + "_" + str(op))
        elif k == "dict":
            for pc in spec:
                cs: str = str(pc)
                v: PyVal = spec[pc]
                if pyval_kind(v) == "list":
                    for op2 in v:
                        cols.append(cs)
                        ops.append(str(op2))
                        names.append(cs + "_" + str(op2))
                else:
                    cols.append(cs)
                    ops.append(str(v))
                    names.append(cs)
        else:
            raise TypeError("agg() expects a str, list or dict specification")
        return self._agg_frame(ops, cols, names)

    def aggregate(self: Ref[DataFrameGroupBy], spec: PyVal) -> DataFrame:
        return self.agg(spec)

    def get_group(self: Ref[DataFrameGroupBy], key: PyVal) -> DataFrame:
        labels: list[PyVal] = self._labels()
        for g in range(len(labels)):
            if labels[g] == key:
                return self.frame._take_rows(self.groups[g])
        raise KeyError(f"{key!r}")

    def apply(self: Ref[DataFrameGroupBy], func: Callable[[DataFrame], PyVal]) -> Series:
        vals: list[PyVal] = []
        for g in self.groups:
            sub: DataFrame = self.frame._take_rows(g)
            vals.append(func(move(sub)))
        return Series(_v=move(vals), _i=self._labels())

    def transform(self: Ref[DataFrameGroupBy], op: str) -> DataFrame:
        names: list[str] = self._numeric_value_cols(op)
        n: int = len(self.frame.index)
        cols: dict[str, list[PyVal]] = {}
        for c in names:
            out: list[PyVal] = []
            for _ in range(n):
                out.append(None)
            for g in self.groups:
                agg: PyVal = _agg_cells(_take(self.frame._cols[c], g), op)
                for p in g:
                    out[p] = agg
            cols[c] = move(out)
        return DataFrame(_c=move(cols), _o=move(names), _i=[v for v in self.frame.index])


def _group_labels(keys: Ref[list[str]], key_rows: Ref[list[list[PyVal]]]) -> list[PyVal]:
    """Group labels: the key value (one key) or a list of key values."""
    out: list[PyVal] = []
    for r in key_rows:
        if len(keys) == 1:
            out.append(r[0])
        else:
            lst: list[PyVal] = [v for v in r]
            out.append(lst)
    return out


@dataclass
class SeriesGroupBy:
    frame: DataFrame
    keys: list[str]
    groups: list[list[int]]
    key_rows: list[list[PyVal]]
    col: str

    @property
    def ngroups(self: Ref[SeriesGroupBy]) -> int:
        return len(self.groups)

    def _agg(self: Ref[SeriesGroupBy], op: str) -> Series:
        """Aggregate the selected column per group into a Series named after it."""
        vals: list[PyVal] = []
        for g in self.groups:
            vals.append(_agg_cells(_take(self.frame._cols[self.col], g), op))
        return Series(name=self.col, _v=move(vals), _i=_group_labels(self.keys, self.key_rows))

    def sum(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("sum")

    def mean(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("mean")

    def min(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("min")

    def max(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("max")

    def count(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("count")

    def size(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("size")

    def median(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("median")

    def std(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("std")

    def var(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("var")

    def first(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("first")

    def last(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("last")

    def nunique(self: Ref[SeriesGroupBy]) -> Series:
        return self._agg("nunique")

    def agg(self: Ref[SeriesGroupBy], op: str) -> Series:
        return self._agg(op)

    def aggregate(self: Ref[SeriesGroupBy], op: str) -> Series:
        return self._agg(op)

    def apply(self: Ref[SeriesGroupBy], func: Callable[[Series], PyVal]) -> Series:
        vals: list[PyVal] = []
        for g in self.groups:
            sub: Series = Series(name=self.col, _v=_take(self.frame._cols[self.col], g),
                                 _i=_take(self.frame.index, g))
            vals.append(func(move(sub)))
        return Series(name=self.col, _v=move(vals), _i=_group_labels(self.keys, self.key_rows))

    def transform(self: Ref[SeriesGroupBy], op: str) -> Series:
        n: int = len(self.frame.index)
        out: list[PyVal] = []
        for _ in range(n):
            out.append(None)
        for g in self.groups:
            agg: PyVal = _agg_cells(_take(self.frame._cols[self.col], g), op)
            for p in g:
                out[p] = agg
        return Series(name=self.col, _v=move(out), _i=[v for v in self.frame.index])


# ----------------------------------------------------------------------------- reshape


def _pivot(df: Ref[DataFrame], values: PyVal, index: PyVal, columns: PyVal, aggfunc: str,
           fill_value: PyVal, strict: bool) -> DataFrame:
    """Shared pivot/pivot_table: rows by index keys, one column per distinct column value."""
    keys: list[str] = _list_of_names(index)
    colkey: str = str(columns)
    if len(keys) == 0 or pyval_kind(columns) == "NoneType":
        raise ValueError("pivot requires index and columns")
    vals: list[str] = _list_of_names(values)
    if len(vals) == 0:
        for c in df.columns:
            if c not in keys and c != colkey:
                d: str = _dtype_of(df._cols[c])
                if strict or d == "int64" or d == "float64" or d == "bool":
                    vals.append(c)
    keycols: list[list[PyVal]] = []
    for k in keys:
        keycols.append(df._col(k))
    colvals: list[PyVal] = df._col(colkey)
    n: int = len(df.index)
    gid: dict[str, int] = {}
    groups: list[list[int]] = []
    firsts: list[int] = []
    cid: dict[str, int] = {}
    cfirsts: list[int] = []
    for i in range(n):
        rk: str = _row_key(keycols, i)
        if rk in gid:
            groups[gid[rk]].append(i)
        else:
            gid[rk] = len(groups)
            groups.append([i])
            firsts.append(i)
        ck: str = _hkey(colvals[i])
        if ck not in cid:
            cid[ck] = len(cfirsts)
            cfirsts.append(i)
    gkeys: list[list[PyVal]] = []
    asc: list[bool] = []
    for kc in keycols:
        gkeys.append(_take(kc, firsts))
        asc.append(True)
    gorder: list[int] = _argsort(gkeys, asc, len(groups))
    ckeys: list[list[PyVal]] = [_take(colvals, cfirsts)]
    corder: list[int] = _argsort(ckeys, [True], len(cfirsts))
    out: dict[str, list[PyVal]] = {}
    order: list[str] = []
    idx: list[PyVal] = []
    if len(keys) == 1:
        for g in gorder:
            idx.append(keycols[0][firsts[g]])
    else:
        for k2 in range(len(keys)):
            order.append(keys[k2])
            out[keys[k2]] = [keycols[k2][firsts[g2]] for g2 in gorder]
        idx = _range_index(len(groups))
    for v in vals:
        for c2 in corder:
            cv: PyVal = colvals[cfirsts[c2]]
            name: str = str(cv)
            if len(vals) > 1:
                name = v + "_" + str(cv)
            cells: list[PyVal] = []
            for g3 in gorder:
                got: list[PyVal] = []
                for p in groups[g3]:
                    if _hkey(colvals[p]) == _hkey(cv):
                        got.append(df._cols[v][p])
                if strict and len(got) > 1:
                    raise ValueError("Index contains duplicate entries, cannot reshape")
                if len(got) == 0:
                    cells.append(fill_value)
                else:
                    agg: PyVal = _agg_cells(got, aggfunc)
                    if isna(agg):
                        cells.append(fill_value)
                    else:
                        cells.append(agg)
            order.append(name)
            out[name] = move(cells)
    return DataFrame(_c=move(out), _o=move(order), _i=move(idx))


def crosstab(index: Ref[Series], columns: Ref[Series]) -> DataFrame:
    """Frequency table of two equal-length Series (missing pairs dropped)."""
    n: int = len(index.values)
    if len(columns.values) != n:
        raise ValueError("All arrays must be of the same length")
    rid: dict[str, int] = {}
    rfirst: list[int] = []
    cid: dict[str, int] = {}
    cfirst: list[int] = []
    for i in range(n):
        if isna(index.values[i]) or isna(columns.values[i]):
            continue
        rk: str = _hkey(index.values[i])
        if rk not in rid:
            rid[rk] = len(rfirst)
            rfirst.append(i)
        ck: str = _hkey(columns.values[i])
        if ck not in cid:
            cid[ck] = len(cfirst)
            cfirst.append(i)
    rorder: list[int] = _argsort([_take(index.values, rfirst)], [True], len(rfirst))
    corder: list[int] = _argsort([_take(columns.values, cfirst)], [True], len(cfirst))
    rpos: dict[str, int] = {}
    for a in range(len(rorder)):
        rpos[_hkey(index.values[rfirst[rorder[a]]])] = a
    cpos: dict[str, int] = {}
    for b in range(len(corder)):
        cpos[_hkey(columns.values[cfirst[corder[b]]])] = b
    counts: list[list[int]] = []
    for _ in rorder:
        row: list[int] = []
        for _2 in corder:
            row.append(0)
        counts.append(move(row))
    for i2 in range(n):
        if isna(index.values[i2]) or isna(columns.values[i2]):
            continue
        r: int = rpos[_hkey(index.values[i2])]
        c: int = cpos[_hkey(columns.values[i2])]
        counts[r][c] = counts[r][c] + 1
    out: dict[str, list[PyVal]] = {}
    order: list[str] = []
    for b2 in range(len(corder)):
        name: str = str(columns.values[cfirst[corder[b2]]])
        order.append(name)
        col: list[PyVal] = []
        for a2 in range(len(rorder)):
            col.append(counts[a2][b2])
        out[name] = move(col)
    idx: list[PyVal] = []
    for a3 in rorder:
        idx.append(index.values[rfirst[a3]])
    return DataFrame(_c=move(out), _o=move(order), _i=move(idx))


# ----------------------------------------------------------------------------- query / eval


def _is_name_char(c: str) -> bool:
    """True for an identifier character."""
    return (c >= "a" and c <= "z") or (c >= "A" and c <= "Z") or (c >= "0" and c <= "9") \
        or c == "_"


@dataclass
class _Query:
    toks: list[str]
    kinds: list[str]
    pos: int

    def peek(self: Ref[_Query]) -> str:
        """Current token text ("" at end)."""
        if self.pos >= len(self.toks):
            return ""
        return self.toks[self.pos]

    def kind(self: Ref[_Query]) -> str:
        """Current token kind ("" at end)."""
        if self.pos >= len(self.toks):
            return ""
        return self.kinds[self.pos]

    def take(self: Mut[_Query]) -> str:
        """Consume and return the current token."""
        t: str = self.peek()
        self.pos += 1
        return t

    def expect(self: Mut[_Query], t: str) -> None:
        """Consume a required token."""
        if self.peek() != t:
            raise ValueError(f"expected '{t}' in query at token {self.pos}")
        self.pos += 1

    def _bcast(self: Ref[_Query], v: PyVal, n: int) -> list[PyVal]:
        """Scalar as an n-row column."""
        out: list[PyVal] = []
        for _ in range(n):
            out.append(v)
        return out

    def _scalar(self: Mut[_Query]) -> PyVal:
        """One literal token as a cell."""
        k: str = self.kind()
        t: str = self.take()
        if k == "num":
            if t.find(".") >= 0 or t.find("e") >= 0:
                return float(t)
            return int(t)
        if k == "str":
            return t
        if t == "True":
            return True
        if t == "False":
            return False
        if t == "None":
            return None
        raise ValueError(f"unexpected token '{t}' in query")

    def _list(self: Mut[_Query]) -> list[PyVal]:
        """Bracketed literal list."""
        self.expect("[")
        out: list[PyVal] = []
        while self.peek() != "]":
            out.append(self._scalar())
            if self.peek() == ",":
                self.take()
        self.expect("]")
        return out

    def expr(self: Mut[_Query], df: Ref[DataFrame]) -> list[PyVal]:
        """or-expression."""
        left: list[PyVal] = self.and_(df)
        while self.peek() == "or" or self.peek() == "|":
            self.take()
            right: list[PyVal] = self.and_(df)
            for i in range(len(left)):
                left[i] = bool(left[i]) or bool(right[i])
        return left

    def and_(self: Mut[_Query], df: Ref[DataFrame]) -> list[PyVal]:
        """and-expression."""
        left: list[PyVal] = self.not_(df)
        while self.peek() == "and" or self.peek() == "&":
            self.take()
            right: list[PyVal] = self.not_(df)
            for i in range(len(left)):
                left[i] = bool(left[i]) and bool(right[i])
        return left

    def not_(self: Mut[_Query], df: Ref[DataFrame]) -> list[PyVal]:
        """not-expression."""
        if self.peek() == "not" or self.peek() == "~":
            self.take()
            inner: list[PyVal] = self.not_(df)
            for i in range(len(inner)):
                inner[i] = not bool(inner[i])
            return inner
        return self.cmp(df)

    def cmp(self: Mut[_Query], df: Ref[DataFrame]) -> list[PyVal]:
        """comparison / membership."""
        left: list[PyVal] = self.arith(df)
        op: str = self.peek()
        if op == "==" or op == "!=" or op == "<" or op == "<=" or op == ">" or op == ">=":
            self.take()
            right: list[PyVal] = self.arith(df)
            for i in range(len(left)):
                left[i] = _compare(left[i], right[i], op)
            return left
        negate: bool = False
        if op == "not":
            self.take()
            negate = True
            if self.peek() != "in":
                raise ValueError("expected 'in' after 'not' in query")
        if self.peek() == "in":
            self.take()
            items: list[PyVal] = self._list()
            keys: dict[str, bool] = {}
            for it in items:
                keys[_hkey(it)] = True
            for i2 in range(len(left)):
                hit: bool = _hkey(left[i2]) in keys
                if negate:
                    hit = not hit
                left[i2] = hit
        return left

    def arith(self: Mut[_Query], df: Ref[DataFrame]) -> list[PyVal]:
        """additive expression."""
        left: list[PyVal] = self.term(df)
        while self.peek() == "+" or self.peek() == "-":
            op: str = self.take()
            right: list[PyVal] = self.term(df)
            for i in range(len(left)):
                left[i] = _arith(left[i], right[i], op)
        return left

    def term(self: Mut[_Query], df: Ref[DataFrame]) -> list[PyVal]:
        """multiplicative expression."""
        left: list[PyVal] = self.unary(df)
        while self.peek() == "*" or self.peek() == "/" or self.peek() == "//" \
                or self.peek() == "%" or self.peek() == "**":
            op: str = self.take()
            right: list[PyVal] = self.unary(df)
            for i in range(len(left)):
                left[i] = _arith(left[i], right[i], op)
        return left

    def unary(self: Mut[_Query], df: Ref[DataFrame]) -> list[PyVal]:
        """unary minus / atom."""
        if self.peek() == "-":
            self.take()
            inner: list[PyVal] = self.unary(df)
            for i in range(len(inner)):
                inner[i] = _arith(0, inner[i], "-")
            return inner
        return self.atom(df)

    def atom(self: Mut[_Query], df: Ref[DataFrame]) -> list[PyVal]:
        """literal, column reference or parenthesised expression."""
        n: int = len(df.index)
        k: str = self.kind()
        t: str = self.peek()
        if t == "(":
            self.take()
            inner: list[PyVal] = self.expr(df)
            self.expect(")")
            return inner
        if k == "name" and t != "True" and t != "False" and t != "None":
            self.take()
            if t == "index":
                return [v for v in df.index]
            if t not in df._cols:
                raise KeyError(f"name '{t}' is not defined")
            return [v for v in df._cols[t]]
        sc: PyVal = self._scalar()
        return self._bcast(sc, n)


def _tokenize(text: str) -> _Query:
    """Token stream of a query expression."""
    toks: list[str] = []
    kinds: list[str] = []
    i: int = 0
    n: int = len(text)
    while i < n:
        c: str = text[i]
        if c == " " or c == "\t" or c == "\n":
            i += 1
        elif (c >= "0" and c <= "9") or (c == "." and i + 1 < n and text[i + 1] >= "0"
                                          and text[i + 1] <= "9"):
            j: int = i
            while j < n and ((text[j] >= "0" and text[j] <= "9") or text[j] == "."
                             or text[j] == "e"):
                j += 1
            toks.append(text[i:j])
            kinds.append("num")
            i = j
        elif c == "'" or c == '"':
            j2: int = i + 1
            while j2 < n and text[j2] != c:
                j2 += 1
            toks.append(text[i + 1:j2])
            kinds.append("str")
            i = j2 + 1
        elif c == "`":
            j3: int = i + 1
            while j3 < n and text[j3] != "`":
                j3 += 1
            toks.append(text[i + 1:j3])
            kinds.append("name")
            i = j3 + 1
        elif _is_name_char(c):
            j4: int = i
            while j4 < n and _is_name_char(text[j4]):
                j4 += 1
            toks.append(text[i:j4])
            kinds.append("name")
            i = j4
        else:
            two: str = text[i:i + 2]
            if two == "==" or two == "!=" or two == "<=" or two == ">=" or two == "//" \
                    or two == "**":
                toks.append(two)
                i += 2
            elif c in "<>&|~+-*/%()[],":
                toks.append(c)
                i += 1
            elif c == "@":
                raise ValueError("query(): '@variable' references are not supported")
            else:
                raise ValueError(f"unexpected character '{c}' in query")
            kinds.append("op")
    return _Query(move(toks), move(kinds), 0)


def _eval_expr(df: Ref[DataFrame], text: str) -> list[PyVal]:
    """Evaluate a query expression to one cell per row."""
    q: _Query = _tokenize(text)
    out: list[PyVal] = q.expr(df)
    if q.pos < len(q.toks):
        raise ValueError(f"unexpected token '{q.peek()}' in query")
    return out


# ----------------------------------------------------------------------------- merge / concat


def _list_of_names(v: PyVal) -> list[str]:
    """Column-name list from a str or list PyVal (empty for None)."""
    out: list[str] = []
    k: str = pyval_kind(v)
    if k == "list":
        for c in v:
            out.append(str(c))
    elif k != "NoneType":
        out.append(str(v))
    return out


def merge(left: Ref[DataFrame], right: Ref[DataFrame], on: PyVal = None,
          how: str = "inner", left_on: PyVal = None, right_on: PyVal = None,
          suffixes: PyVal = None) -> DataFrame:
    """SQL-style join of two frames on key columns (inner/left/right/outer)."""
    lkeys: list[str] = _list_of_names(on)
    rkeys: list[str] = _list_of_names(on)
    if len(lkeys) == 0:
        lkeys = _list_of_names(left_on)
        rkeys = _list_of_names(right_on)
    if len(lkeys) == 0:
        for c in left.columns:
            if c in right._cols:
                lkeys.append(c)
                rkeys.append(c)
    if len(lkeys) == 0 or len(lkeys) != len(rkeys):
        raise ValueError("No common columns to perform merge on")
    sfx_l: str = "_x"
    sfx_r: str = "_y"
    if pyval_kind(suffixes) == "list":
        sfx_l = str(suffixes[0])
        sfx_r = str(suffixes[1])
    lcols: list[list[PyVal]] = []
    for c in lkeys:
        lcols.append(left._col(c))
    rcols: list[list[PyVal]] = []
    for c in rkeys:
        rcols.append(right._col(c))
    rindex: dict[str, list[int]] = {}
    for j in range(len(right.index)):
        k: str = _row_key(rcols, j)
        if k in rindex:
            rindex[k].append(j)
        else:
            rindex[k] = [j]
    lpos: list[int] = []
    rpos: list[int] = []
    matched_r: dict[int, bool] = {}
    for i in range(len(left.index)):
        k2: str = _row_key(lcols, i)
        if k2 in rindex:
            for j2 in rindex[k2]:
                lpos.append(i)
                rpos.append(j2)
                matched_r[j2] = True
        elif how == "left" or how == "outer":
            lpos.append(i)
            rpos.append(-1)
    if how == "right" or how == "outer":
        for j3 in range(len(right.index)):
            if j3 not in matched_r:
                lpos.append(-1)
                rpos.append(j3)
    rkey_set: dict[str, bool] = {}
    for c in rkeys:
        rkey_set[c] = True
    lkey_set: dict[str, bool] = {}
    for c in lkeys:
        lkey_set[c] = True
    out: dict[str, list[PyVal]] = {}
    order: list[str] = []
    for c in left.columns:
        name: str = c
        if c not in lkey_set and c in right._cols and c not in rkey_set:
            name = c + sfx_l
        vals: list[PyVal] = []
        for r in range(len(lpos)):
            if lpos[r] >= 0:
                vals.append(left._cols[c][lpos[r]])
            elif c in lkey_set:
                ki: int = 0
                for q in range(len(lkeys)):
                    if lkeys[q] == c:
                        ki = q
                vals.append(right._cols[rkeys[ki]][rpos[r]])
            else:
                vals.append(None)
        order.append(name)
        out[name] = move(vals)
    for c2 in right.columns:
        if c2 in rkey_set:
            continue
        name2: str = c2
        if c2 in left._cols and c2 not in lkey_set:
            name2 = c2 + sfx_r
        vals2: list[PyVal] = []
        for r2 in range(len(rpos)):
            if rpos[r2] >= 0:
                vals2.append(right._cols[c2][rpos[r2]])
            else:
                vals2.append(None)
        order.append(name2)
        out[name2] = move(vals2)
    return DataFrame(_c=move(out), _o=move(order), _i=_range_index(len(lpos)))


def concat(objs: Ref[list[DataFrame]], axis: int = 0, ignore_index: bool = False) -> DataFrame:
    """Stack frames vertically (axis=0, union of columns) or side by side (axis=1)."""
    out: dict[str, list[PyVal]] = {}
    order: list[str] = []
    idx: list[PyVal] = []
    if axis == 1:
        n: int = 0
        for df in objs:
            if len(df.index) > n:
                n = len(df.index)
        for df2 in objs:
            for c in df2.columns:
                name: str = c
                if name in out:
                    name = c + "_" + str(len(order))
                vals: list[PyVal] = []
                for i in range(n):
                    if i < len(df2.index):
                        vals.append(df2._cols[c][i])
                    else:
                        vals.append(None)
                order.append(name)
                out[name] = move(vals)
        if len(objs) > 0:
            idx = [v for v in objs[0].index]
        while len(idx) < n:
            nxt: int = len(idx)
            idx.append(nxt)
        return DataFrame(_c=move(out), _o=move(order), _i=move(idx))
    total: int = 0
    for df3 in objs:
        total += len(df3.index)
        for c2 in df3.columns:
            if c2 not in out:
                out[c2] = []
                order.append(c2)
    for df4 in objs:
        for c3 in order:
            if c3 in df4._cols:
                for v in df4._cols[c3]:
                    out[c3].append(v)
            else:
                for _ in range(len(df4.index)):
                    out[c3].append(None)
        for lab in df4.index:
            idx.append(lab)
    if ignore_index:
        idx = _range_index(total)
    return DataFrame(_c=move(out), _o=move(order), _i=move(idx))


# ----------------------------------------------------------------------------- CSV


def _csv_cell(v: PyVal) -> str:
    """CSV text of a cell (missing -> empty)."""
    if isna(v):
        return ""
    if pyval_kind(v) == "float":
        return str(float(v))
    if _is_dt(v):
        return _dt_text(v, True)
    return str(v)


def _csv_quote(s: str, sep: str) -> str:
    """Quote a CSV field when it contains the separator, quotes or newlines."""
    if s.find(sep) >= 0 or s.find('"') >= 0 or s.find("\n") >= 0 or s.find("\r") >= 0:
        return '"' + s.replace('"', '""') + '"'
    return s


def _csv_rows(text: str, sep: str) -> list[list[str]]:
    """Split CSV text into rows of fields (RFC 4180 quoting)."""
    rows: list[list[str]] = []
    row: list[str] = []
    field: str = ""
    quoted: bool = False
    i: int = 0
    n: int = len(text)
    while i < n:
        ch: str = text[i]
        if quoted:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field = field + '"'
                    i += 1
                else:
                    quoted = False
            else:
                field = field + ch
        elif ch == '"':
            quoted = True
        elif ch == sep:
            row.append(field)
            field = ""
        elif ch == "\n" or ch == "\r":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append(field)
            field = ""
            rows.append(move(row))
            row = []
        else:
            field = field + ch
        i += 1
    if len(field) > 0 or len(row) > 0:
        row.append(field)
        rows.append(move(row))
    return rows


def _is_int_text(s: str) -> bool:
    """True for an optionally signed run of ASCII digits."""
    body: str = s
    if body.startswith("-") or body.startswith("+"):
        body = body[1:]
    if len(body) == 0:
        return False
    for c in body:
        if c < "0" or c > "9":
            return False
    return True


def _is_float_text(s: str) -> bool:
    """True for a decimal float literal (digits, one dot, optional exponent)."""
    body: str = s
    if body.startswith("-") or body.startswith("+"):
        body = body[1:]
    if len(body) == 0:
        return False
    epos: int = body.find("e")
    if epos < 0:
        epos = body.find("E")
    exp: str = ""
    if epos >= 0:
        exp = body[epos + 1:]
        body = body[:epos]
        if not _is_int_text(exp):
            return False
    digits: int = 0
    dots: int = 0
    for c in body:
        if c == ".":
            dots += 1
        elif c < "0" or c > "9":
            return False
        else:
            digits += 1
    return digits > 0 and dots <= 1


def _parse_cell(s: str) -> PyVal:
    """Infer a cell value from CSV text: int, float, bool, missing or str."""
    if s == "" or s == "NaN" or s == "nan" or s == "NA" or s == "null" or s == "None":
        return None
    if _is_int_text(s):
        return int(s)
    if _is_float_text(s):
        return float(s)
    if s == "True" or s == "true" or s == "TRUE":
        return True
    if s == "False" or s == "false" or s == "FALSE":
        return False
    return s


def read_csv_text(text: str, sep: str = ",", header: bool = True,
                  parse_dates: PyVal = None) -> DataFrame:
    """Parse CSV text into a DataFrame with inferred column types."""
    rows: list[list[str]] = _csv_rows(text, sep)
    names: list[str] = []
    start: int = 0
    if len(rows) == 0:
        return DataFrame()
    if header:
        for h in rows[0]:
            names.append(h)
        start = 1
    else:
        for i in range(len(rows[0])):
            names.append(str(i))
    index_col: bool = header and len(names) > 0 and names[0] == ""
    cols: dict[str, list[PyVal]] = {}
    order: list[str] = []
    idx: list[PyVal] = []
    for j in range(len(names)):
        if index_col and j == 0:
            continue
        cols[names[j]] = []
        order.append(names[j])
    for r in range(start, len(rows)):
        row = rows[r]
        for j2 in range(len(names)):
            cell: str = ""
            if j2 < len(row):
                cell = row[j2]
            if index_col and j2 == 0:
                idx.append(_parse_cell(cell))
            else:
                cols[names[j2]].append(_parse_cell(cell))
    if not index_col:
        idx = _range_index(len(rows) - start)
    for dc in _list_of_names(parse_dates):
        if dc not in cols:
            raise ValueError(f"Missing column provided to 'parse_dates': '{dc}'")
        cols[dc] = [_to_dt_cell(v, "", False) for v in cols[dc]]
    return DataFrame(_c=move(cols), _o=move(order), _i=move(idx))


def read_csv(path: str, sep: str = ",", header: bool = True,
             parse_dates: PyVal = None) -> DataFrame:
    """Read a CSV file into a DataFrame."""
    text: str = ""
    with open(path) as f:
        text = f.read()
    return read_csv_text(text, sep, header, parse_dates)


# ----------------------------------------------------------------------------- json


def _json_cell(v: PyVal, date_format: str) -> PyVal:
    """JSON-ready cell: missing -> null, datetimes -> epoch ms or ISO text."""
    if isna(v):
        return None
    if _is_dt(v):
        if date_format == "iso":
            return _dt_iso(v) + ".000"
        d: Dt = _dt_parse(v)
        return _dt_epoch_ms(d)
    return v


def _dt_epoch_ms(d: Ref[Dt]) -> int:
    """Milliseconds since the Unix epoch."""
    days: int = _days_from_civil(d.year, d.month, d.day)
    return (days * 86400 + d.hour * 3600 + d.minute * 60 + d.second) * 1000


def _json_label(v: PyVal) -> str:
    """Object key text of an index label."""
    if _is_dt(v):
        return _dt_iso(v)
    return str(v)


def _emit_json(obj: PyVal, path: PyVal, indent: int) -> str:
    """Serialise like pandas (compact, ASCII, escaped slashes) and optionally write a file."""
    text: str = _json_dumps(obj, True, False, indent <= 0)
    text = text.replace("/", "\\/")
    if pyval_kind(path) == "str":
        with open(str(path), "w") as f:
            f.write(text)
    return text


def _json_index_label(k: str) -> PyVal:
    """Index label from a JSON object key (integer text becomes an int)."""
    if _is_int_text(k):
        return int(k)
    return k


def read_json_text(text: str, orient: str = "columns") -> DataFrame:
    """Parse JSON text produced by to_json (columns/records/index/split/values orients)."""
    obj: PyVal = _json_loads(text)
    k: str = pyval_kind(obj)
    if orient == "records" or (k == "list" and orient == "columns"):
        return DataFrame(obj)
    if orient == "values":
        return DataFrame(obj)
    if orient == "split":
        cols: dict[str, list[PyVal]] = {}
        order: list[str] = []
        for c in obj["columns"]:
            order.append(str(c))
            cols[str(c)] = []
        for row in obj["data"]:
            for ci in range(len(order)):
                cols[order[ci]].append(row[ci])
        return DataFrame(_c=move(cols), _o=move(order), _i=_unbox_list(obj["index"]))
    if orient == "index":
        cols2: dict[str, list[PyVal]] = {}
        order2: list[str] = []
        idx2: list[PyVal] = []
        for key in obj:
            idx2.append(_json_index_label(str(key)))
            rec: PyVal = obj[key]
            for ck in rec:
                cs: str = str(ck)
                if cs not in cols2:
                    cols2[cs] = []
                    order2.append(cs)
        for key2 in obj:
            rec2: PyVal = obj[key2]
            for c2 in order2:
                if c2 in rec2:
                    cols2[c2].append(rec2[c2])
                else:
                    cols2[c2].append(None)
        return DataFrame(_c=move(cols2), _o=move(order2), _i=move(idx2))
    cols3: dict[str, list[PyVal]] = {}
    order3: list[str] = []
    idx3: list[PyVal] = []
    first: bool = True
    for col in obj:
        name: str = str(col)
        order3.append(name)
        vals: list[PyVal] = []
        for lbl in obj[col]:
            if first:
                idx3.append(_json_index_label(str(lbl)))
            vals.append(obj[col][lbl])
        first = False
        cols3[name] = move(vals)
    return DataFrame(_c=move(cols3), _o=move(order3), _i=move(idx3))


def read_json(path: str, orient: str = "columns") -> DataFrame:
    """Read a JSON file into a DataFrame."""
    text: str = ""
    with open(path) as f:
        text = f.read()
    return read_json_text(text, orient)