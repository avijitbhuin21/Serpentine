"""serp-coil (Coil): a numpy drop-in for Serpentine.

`ndarray` is a dense row-major array of float64 storage tagged with a numpy dtype
name (`float64`, `int64`, `bool`) so printing, arithmetic result types and
comparisons follow numpy. Operator dunders, broadcasting (scalars, 1-D vs 2-D,
size-1 axes), reductions, ufuncs, sorting and small dense linear algebra are
written in the Serpentine subset so the same file runs under CPython and compiles
natively. See README.md for the divergences from numpy.
"""
from __future__ import annotations

from serpentine import Mut, Owned, PyVal, Ref, dataclass, move, pyval_kind
from serp_math import (acos as _m_acos, asin as _m_asin, atan as _m_atan, atan2 as _m_atan2, cbrt as _m_cbrt, ceil as _m_ceil, cos as _m_cos, cosh as _m_cosh, exp as _m_exp, exp2 as _m_exp2, expm1 as _m_expm1, fabs as _m_fabs, floor as _m_floor, isinf as _m_isinf, isnan as _m_isnan, log as _m_log, log10 as _m_log10, log1p as _m_log1p, log2 as _m_log2, sin as _m_sin, sinh as _m_sinh, sqrt as _m_sqrt, tan as _m_tan, tanh as _m_tanh, trunc as _m_trunc,
                       inf, nan)

pi: float = 3.141592653589793
e: float = 2.718281828459045
euler_gamma: float = 0.5772156649015329
float64: str = "float64"
int64: str = "int64"
bool_: str = "bool"

_LINEWIDTH: int = 75
_PRECISION: int = 8
_THRESHOLD: int = 1000
_EDGEITEMS: int = 3


def _spaces(n: int) -> str:
    """Return `n` spaces."""
    s: str = ""
    i: int = 0
    while i < n:
        s = s + " "
        i = i + 1
    return s


def _pad_left(s: str, width: int) -> str:
    """Right-justify `s` in `width` columns."""
    return _spaces(width - len(s)) + s


def _pad_right(s: str, width: int) -> str:
    """Left-justify `s` in `width` columns."""
    return s + _spaces(width - len(s))


def _norm_dtype(name: str) -> str:
    """Map a numpy dtype spelling onto the three storage dtypes."""
    if name == "" or name == "float64" or name == "float" or name == "f8" or name == "double" \
            or name == "float32" or name == "f4" or name == "d":
        return "float64"
    if name == "int64" or name == "int" or name == "i8" or name == "int32" or name == "i4" \
            or name == "long" or name == "intp" or name == "uint8" or name == "int8" \
            or name == "int16" or name == "uint64" or name == "uint32" or name == "uint16":
        return "int64"
    if name == "bool" or name == "bool_" or name == "?" or name == "b1":
        return "bool"
    raise TypeError("data type '" + name + "' not understood")


def _cast(v: float, dtype: str) -> float:
    """Coerce a stored value to the representable set of `dtype`."""
    if dtype == "float64":
        return v
    if dtype == "bool":
        if v != 0.0:
            return 1.0
        return 0.0
    if _m_isnan(v) or _m_isinf(v):
        return 0.0
    return float(_m_trunc(v))


def _size_of(shape: Ref[list[int]]) -> int:
    """Number of elements in a shape."""
    n: int = 1
    for s in shape:
        n = n * s
    return n


def _shape_tuple(shape: Ref[list[int]]) -> str:
    """numpy's `repr(tuple)` spelling of a shape: `(3,)`, `(2, 3)`."""
    if len(shape) == 1:
        return "(" + str(shape[0]) + ",)"
    parts: list[str] = [str(s) for s in shape]
    return "(" + ", ".join(parts) + ")"


def _shape_compact(shape: Ref[list[int]]) -> str:
    """numpy's error-message spelling of a shape: `(3,)`, `(2,3)`."""
    if len(shape) == 1:
        return "(" + str(shape[0]) + ",)"
    parts: list[str] = [str(s) for s in shape]
    return "(" + ",".join(parts) + ")"


def _same_shape(a: Ref[list[int]], b: Ref[list[int]]) -> bool:
    """Whether two shapes are identical."""
    if len(a) != len(b):
        return False
    i: int = 0
    while i < len(a):
        if a[i] != b[i]:
            return False
        i = i + 1
    return True


def _copy_shape(shape: Ref[list[int]]) -> list[int]:
    """Fresh copy of a shape list."""
    return [s for s in shape]


def _rint(x: float) -> float:
    """Round half to even (numpy `rint`)."""
    if _m_isnan(x) or _m_isinf(x):
        return x
    f: float = float(_m_floor(x))
    d: float = x - f
    r: float = f
    if d > 0.5:
        r = f + 1.0
    elif d == 0.5:
        h: float = f / 2.0
        if h != float(_m_floor(h)):
            r = f + 1.0
    if r == 0.0 and x < 0.0:
        return x * 0.0
    return r


def _repr_digits(x: float) -> tuple[str, int]:
    """Shortest round-trip digits of |x| and the decimal point position (value = 0.DIGITS * 10**point... as D[:point].D[point:])."""
    s: str = str(x)
    if s[0] == "-":
        s = s[1:]
    exp10: int = 0
    epos: int = s.find("e")
    if epos >= 0:
        exp10 = int(s[epos + 1:])
        s = s[:epos]
    dot: int = s.find(".")
    ip: str = s
    fp: str = ""
    if dot >= 0:
        ip = s[:dot]
        fp = s[dot + 1:]
    digits: str = ip + fp
    point: int = len(ip) + exp10
    lead: int = 0
    while lead < len(digits) - 1 and digits[lead] == "0":
        lead = lead + 1
        point = point - 1
    digits = digits[lead:]
    end: int = len(digits)
    while end > 1 and digits[end - 1] == "0":
        end = end - 1
    digits = digits[:end]
    if digits == "0":
        point = 1
    return (digits, point)


def _round_digits(digits: str, keep: int) -> tuple[str, int]:
    """Round a digit string to `keep` significant digits (half-up); returns digits and carry (0/1)."""
    if len(digits) <= keep:
        return (digits, 0)
    head: str = digits[:keep]
    up: bool = digits[keep] >= "5"
    if not up:
        return (head, 0)
    out: str = ""
    i: int = len(head) - 1
    carry: bool = True
    while i >= 0:
        c: str = head[i]
        if carry:
            if c == "9":
                out = "0" + out
            else:
                out = chr(ord(c) + 1) + out
                carry = False
        else:
            out = c + out
        i = i - 1
    if carry:
        return ("1" + out, 1)
    return (out, 0)


def _strip_zeros(s: str) -> str:
    """Drop trailing zeros from a fraction string."""
    end: int = len(s)
    while end > 0 and s[end - 1] == "0":
        end = end - 1
    return s[:end]


def _positional_parts(x: float) -> tuple[str, str]:
    """Integer part (with sign) and trimmed fraction of x rounded to 8 places (numpy maxprec/unique)."""
    dp: tuple[str, int] = _repr_digits(x)
    digits: str = dp[0]
    point: int = dp[1]
    keep: int = point + _PRECISION
    if len(digits) > keep:
        if keep < 0:
            digits = "0"
            point = 1
        elif keep == 0:
            if digits[0] >= "5":
                digits = "1"
                point = point + 1
            else:
                digits = "0"
                point = 1
        else:
            rd: tuple[str, int] = _round_digits(digits, keep)
            digits = rd[0]
            point = point + rd[1]
    ip: str = "0"
    fp: str = ""
    if point <= 0:
        fp = _spaces(-point).replace(" ", "0") + digits
    elif point >= len(digits):
        ip = digits + _spaces(point - len(digits)).replace(" ", "0")
    else:
        ip = digits[:point]
        fp = digits[point:]
    fp = _strip_zeros(fp)
    if ip == "0" and fp == "" and digits != "0":
        ip = "0"
    if x < 0.0 or (x == 0.0 and str(x)[0] == "-"):
        ip = "-" + ip
    return (ip, fp)


def _sci_parts(x: float) -> tuple[str, str, int]:
    """Signed leading digit, fraction digits (≤8, trimmed) and exponent of x in scientific form."""
    dp: tuple[str, int] = _repr_digits(x)
    digits: str = dp[0]
    point: int = dp[1]
    rd: tuple[str, int] = _round_digits(digits, _PRECISION + 1)
    digits = rd[0]
    point = point + rd[1]
    if digits == "0":
        point = 1
    lead: str = digits[:1]
    frac: str = _strip_zeros(digits[1:])
    if x < 0.0 or (x == 0.0 and str(x)[0] == "-"):
        lead = "-" + lead
    return (lead, frac, point - 1)


def _exp_str(e10: int, width: int) -> str:
    """numpy exponent spelling: sign plus at least `width` digits."""
    sign: str = "+"
    v: int = e10
    if v < 0:
        sign = "-"
        v = -v
    d: str = str(v)
    while len(d) < width:
        d = "0" + d
    return sign + d


def _format_floats(vals: Ref[list[float]]) -> list[str]:
    """Format floats the way numpy's FloatingFormat does (maxprec, precision 8, sign '-')."""
    finite: list[float] = []
    has_neg_inf: bool = False
    for v in vals:
        if _m_isnan(v):
            continue
        if _m_isinf(v):
            if v < 0.0:
                has_neg_inf = True
            continue
        finite.append(v)
    out: list[str] = []
    if len(finite) == 0:
        for v in vals:
            s: str = "nan"
            if _m_isinf(v):
                if v < 0.0:
                    s = "-inf"
                else:
                    s = "inf"
            out.append(_pad_left(s, 3))
        return out
    max_val: float = 0.0
    min_val: float = 0.0
    seen: bool = False
    for v in finite:
        if v == 0.0:
            continue
        a: float = _m_fabs(v)
        if not seen:
            max_val = a
            min_val = a
            seen = True
        else:
            if a > max_val:
                max_val = a
            if a < min_val:
                min_val = a
    exp_format: bool = False
    if seen:
        if max_val >= 1e8 or min_val < 0.0001 or max_val / min_val > 1000.0:
            exp_format = True
    pad_left: int = 0
    pad_right: int = 0
    if exp_format:
        exp_size: int = 2
        prec: int = 0
        for v in finite:
            sp: tuple[str, str, int] = _sci_parts(v)
            if len(sp[0]) > pad_left:
                pad_left = len(sp[0])
            if len(sp[1]) > prec:
                prec = len(sp[1])
            ev: int = sp[2]
            if ev < 0:
                ev = -ev
            if len(str(ev)) > exp_size:
                exp_size = len(str(ev))
        pad_right = prec + exp_size + 2
        if len(vals) != len(finite):
            offset0: int = pad_right + 1
            cand: int = 3 - offset0
            if cand > pad_left:
                pad_left = cand
            cand = 3 - offset0
            if has_neg_inf:
                cand = 4 - offset0
            if cand > pad_left:
                pad_left = cand
        for v in vals:
            if _m_isnan(v) or _m_isinf(v):
                s2: str = "nan"
                if _m_isinf(v):
                    if v < 0.0:
                        s2 = "-inf"
                    else:
                        s2 = "inf"
                out.append(_pad_left(s2, pad_left + pad_right + 1))
                continue
            sp2: tuple[str, str, int] = _sci_parts(v)
            out.append(_pad_left(sp2[0], pad_left) + "." + _pad_right(sp2[1], prec).replace(" ", "0")
                       + "e" + _exp_str(sp2[2], exp_size))
        return out
    for v in finite:
        pp: tuple[str, str] = _positional_parts(v)
        if len(pp[0]) > pad_left:
            pad_left = len(pp[0])
        if len(pp[1]) > pad_right:
            pad_right = len(pp[1])
    if len(vals) != len(finite):
        offset: int = pad_right + 1
        cand2: int = 3 - offset
        if cand2 > pad_left:
            pad_left = cand2
        cand2 = 3 - offset
        if has_neg_inf:
            cand2 = 4 - offset
        if cand2 > pad_left:
            pad_left = cand2
    for v in vals:
        if _m_isnan(v) or _m_isinf(v):
            s3: str = "nan"
            if _m_isinf(v):
                if v < 0.0:
                    s3 = "-inf"
                else:
                    s3 = "inf"
            out.append(_pad_left(s3, pad_left + pad_right + 1))
            continue
        pp2: tuple[str, str] = _positional_parts(v)
        out.append(_pad_left(pp2[0], pad_left) + "." + _pad_right(pp2[1], pad_right))
    return out


def _format_ints(vals: Ref[list[float]]) -> list[str]:
    """Right-justified integer strings (numpy IntegerFormat)."""
    strs: list[str] = [str(int(v)) for v in vals]
    w: int = 0
    for s in strs:
        if len(s) > w:
            w = len(s)
    return [_pad_left(s, w) for s in strs]


def _format_bools(vals: Ref[list[float]]) -> list[str]:
    """numpy BoolFormat: ` True` / `False` for non-scalar arrays."""
    out: list[str] = []
    for v in vals:
        if v != 0.0:
            out.append(" True")
        else:
            out.append("False")
    return out


def _format_items(vals: Ref[list[float]], dtype: str) -> list[str]:
    """Dispatch element formatting on dtype."""
    if dtype == "int64":
        return _format_ints(vals)
    if dtype == "bool":
        return _format_bools(vals)
    return _format_floats(vals)


def _summarize(vals: Ref[list[float]], shape: Ref[list[int]]) -> list[float]:
    """The leading/trailing `edgeitems` elements along every axis (numpy's width sample)."""
    if len(shape) == 1:
        n: int = shape[0]
        if n <= 2 * _EDGEITEMS:
            return [v for v in vals]
        out: list[float] = []
        i: int = 0
        while i < _EDGEITEMS:
            out.append(vals[i])
            i = i + 1
        i = n - _EDGEITEMS
        while i < n:
            out.append(vals[i])
            i = i + 1
        return out
    rows: int = shape[0]
    cols: int = shape[1]
    out2: list[float] = []
    r: int = 0
    while r < rows:
        if rows > 2 * _EDGEITEMS and r >= _EDGEITEMS and r < rows - _EDGEITEMS:
            r = rows - _EDGEITEMS
            continue
        c: int = 0
        while c < cols:
            if cols > 2 * _EDGEITEMS and c >= _EDGEITEMS and c < cols - _EDGEITEMS:
                c = cols - _EDGEITEMS
                continue
            out2.append(vals[r * cols + c])
            c = c + 1
        r = r + 1
    return out2


def _extend_line(s: str, line: str, word: str, width: int, indent: str) -> tuple[str, str]:
    """numpy `_extendLine`: wrap `line` before `word` when it would overflow `width`."""
    needs_wrap: bool = len(line) + len(word) > width
    if len(line) <= len(indent):
        needs_wrap = False
    if needs_wrap:
        s = s + line.rstrip() + "\n"
        line = indent
    line = line + word
    return (s, line)


def _format_row(items: Ref[list[str]], summary_after: int, indent: str, width: int, sep: str) -> str:
    """Lay out one 1-D run of formatted elements with numpy's wrapping rules; `summary_after` > 0 inserts `...`."""
    n: int = len(items)
    elem_width: int = width - 1
    if len(sep.rstrip()) > 1:
        elem_width = width - len(sep.rstrip())
    s: str = ""
    line: str = indent
    i: int = 0
    while i < n - 1:
        r: tuple[str, str] = _extend_line(s, line, items[i], elem_width, indent)
        s = r[0]
        line = r[1] + sep
        i = i + 1
        if i == summary_after:
            r2: tuple[str, str] = _extend_line(s, line, "...", elem_width, indent)
            s = r2[0]
            line = r2[1] + sep
    r4: tuple[str, str] = _extend_line(s, line, items[n - 1], elem_width, indent)
    s = r4[0] + r4[1]
    return "[" + s[len(indent):] + "]"


def _array_to_string(vals: Ref[list[float]], shape: Ref[list[int]], dtype: str,
                     indent: str, width: int, sep: str) -> str:
    """numpy `array2string` for 1-D and 2-D arrays (edgeitems summarization at size > 1000)."""
    total: int = _size_of(shape)
    if total == 0:
        return "[]"
    summarize: bool = total > _THRESHOLD
    sample: list[float] = [v for v in vals]
    if summarize:
        sample = _summarize(vals, shape)
    strs: list[str] = _format_items(sample, dtype)
    if len(shape) == 1:
        cut: int = 0
        if summarize and shape[0] > 2 * _EDGEITEMS:
            cut = _EDGEITEMS
        return _format_row(strs, cut, indent, width, sep)
    rows: int = shape[0]
    cols: int = shape[1]
    row_indent: str = indent + " "
    row_width: int = width - 1
    line_sep: str = sep.rstrip() + "\n"
    shown_cols: int = cols
    col_cut: int = 0
    if summarize and cols > 2 * _EDGEITEMS:
        shown_cols = 2 * _EDGEITEMS
        col_cut = _EDGEITEMS
    pieces: list[str] = []
    r: int = 0
    pos: int = 0
    while r < rows:
        if summarize and rows > 2 * _EDGEITEMS and r == _EDGEITEMS:
            pieces.append("...")
            r = rows - _EDGEITEMS
            continue
        row: list[str] = []
        c: int = 0
        while c < shown_cols:
            row.append(strs[pos + c])
            c = c + 1
        pos = pos + shown_cols
        pieces.append(_format_row(row, col_cut, row_indent, row_width, sep))
        r = r + 1
    s: str = ""
    k: int = 0
    while k < len(pieces):
        if k > 0:
            s = s + line_sep
        s = s + indent + pieces[k]
        k = k + 1
    return "[" + s[len(indent):] + "]"


@dataclass
class ndarray:
    _data: list[float]
    _shape: list[int]
    dtype: str
    _pos: int = 0

    @property
    def shape(self: Ref[ndarray]) -> list[int]:
        return _copy_shape(self._shape)

    @property
    def ndim(self: Ref[ndarray]) -> int:
        return len(self._shape)

    @property
    def size(self: Ref[ndarray]) -> int:
        return len(self._data)

    @property
    def T(self: Ref[ndarray]) -> ndarray:
        return self.transpose()

    def __len__(self: Ref[ndarray]) -> int:
        return self._shape[0]

    def __str__(self: Ref[ndarray]) -> str:
        return _array_to_string(self._data, self._shape, self.dtype, " ", _LINEWIDTH, " ")

    def __repr__(self: Ref[ndarray]) -> str:
        body: str = _array_to_string(self._data, self._shape, self.dtype, "       ",
                                     _LINEWIDTH - 1, ", ")
        extras: str = ""
        if len(self._data) > _THRESHOLD or (len(self._data) == 0 and len(self._shape) > 1):
            extras = extras + ", shape=" + _shape_tuple(self._shape)
        if len(self._data) == 0:
            extras = extras + ", dtype=" + self.dtype
        return "array(" + body + extras + ")"

    def _flat_index(self: Ref[ndarray], idx: int | tuple[int, int]) -> int:
        """Resolve an int or (row, col) index (negative allowed) to a flat offset."""
        if isinstance(idx, int):
            n: int = self._shape[0]
            i: int = idx
            if i < 0:
                i = i + n
            if i < 0 or i >= n:
                raise IndexError("index " + str(idx) + " is out of bounds for axis 0 with size " + str(n))
            if len(self._shape) == 1:
                return i
            raise IndexError("a row index needs a column too on a 2-D array: use a[i, j] or row(a, i)")
        if len(self._shape) != 2:
            raise IndexError("too many indices for array: array is 1-dimensional, but 2 were indexed")
        r: int = idx[0]
        c: int = idx[1]
        if r < 0:
            r = r + self._shape[0]
        if c < 0:
            c = c + self._shape[1]
        if r < 0 or r >= self._shape[0]:
            raise IndexError("index " + str(idx[0]) + " is out of bounds for axis 0 with size " + str(self._shape[0]))
        if c < 0 or c >= self._shape[1]:
            raise IndexError("index " + str(idx[1]) + " is out of bounds for axis 1 with size " + str(self._shape[1]))
        return r * self._shape[1] + c

    def __getitem__(self: Ref[ndarray], idx: int | tuple[int, int]) -> float:
        return self._data[self._flat_index(idx)]

    def __setitem__(self: Mut[ndarray], idx: Ref[int | tuple[int, int] | ndarray], value: float) -> None:
        v: float = _cast(value, self.dtype)
        if isinstance(idx, ndarray):
            if idx.dtype == "bool":
                if len(idx._data) != len(self._data):
                    raise IndexError("boolean index did not match indexed array along axis 0; size of axis is "
                                     + str(len(self._data)) + " but size of corresponding boolean axis is "
                                     + str(len(idx._data)))
                k: int = 0
                while k < len(self._data):
                    if idx._data[k] != 0.0:
                        self._data[k] = v
                    k = k + 1
                return
            for f in idx._data:
                j: int = int(f)
                if j < 0:
                    j = j + len(self._data)
                if j < 0 or j >= len(self._data):
                    raise IndexError("index " + str(int(f)) + " is out of bounds for axis 0 with size "
                                     + str(len(self._data)))
                self._data[j] = v
            return
        if isinstance(idx, int):
            k1: int = self._flat_index(idx)
            self._data[k1] = v
            return
        if isinstance(idx, tuple):
            k2: int = self._flat_index(idx)
            self._data[k2] = v

    def __iter__(self: Ref[ndarray]) -> ndarray:
        return self

    def __next__(self: Mut[ndarray]) -> float:
        if self._pos >= len(self._data):
            self._pos = 0
            raise StopIteration()
        v: float = self._data[self._pos]
        self._pos = self._pos + 1
        return v

    def item(self: Ref[ndarray], index: int = 0) -> float:
        n: int = len(self._data)
        i: int = index
        if i < 0:
            i = i + n
        if i < 0 or i >= n:
            raise IndexError("index " + str(index) + " is out of bounds for size " + str(n))
        return self._data[i]

    def tolist(self: Ref[ndarray]) -> list[float]:
        return [v for v in self._data]

    def copy(self: Ref[ndarray]) -> ndarray:
        return ndarray([v for v in self._data], _copy_shape(self._shape), self.dtype)

    def astype(self: Ref[ndarray], dtype: str) -> ndarray:
        dt: str = _norm_dtype(dtype)
        return ndarray([_cast(v, dt) for v in self._data], _copy_shape(self._shape), dt)

    def fill(self: Mut[ndarray], value: float) -> None:
        v: float = _cast(value, self.dtype)
        i: int = 0
        while i < len(self._data):
            self._data[i] = v
            i = i + 1

    def reshape(self: Ref[ndarray], shape: Ref[int | tuple[int, int] | list[int]]) -> ndarray:
        sh: list[int] = _resolve_shape(shape, len(self._data))
        return ndarray([v for v in self._data], move(sh), self.dtype)

    def flatten(self: Ref[ndarray]) -> ndarray:
        return ndarray([v for v in self._data], [len(self._data)], self.dtype)

    def ravel(self: Ref[ndarray]) -> ndarray:
        return self.flatten()

    def transpose(self: Ref[ndarray]) -> ndarray:
        if len(self._shape) == 1:
            return self.copy()
        rows: int = self._shape[0]
        cols: int = self._shape[1]
        out: list[float] = []
        c: int = 0
        while c < cols:
            r: int = 0
            while r < rows:
                out.append(self._data[r * cols + c])
                r = r + 1
            c = c + 1
        return ndarray(move(out), [cols, rows], self.dtype)

    def __add__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _ADD)

    def __sub__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _SUB)

    def __mul__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _MUL)

    def __truediv__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _DIV)

    def __floordiv__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _FLOORDIV)

    def __mod__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _MOD)

    def __pow__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _POW)

    def __radd__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop_r(self, other, _ADD)

    def __rsub__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop_r(self, other, _SUB)

    def __rmul__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop_r(self, other, _MUL)

    def __rtruediv__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop_r(self, other, _DIV)

    def __rfloordiv__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop_r(self, other, _FLOORDIV)

    def __rmod__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop_r(self, other, _MOD)

    def __rpow__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop_r(self, other, _POW)

    def __matmul__(self: Ref[ndarray], other: Ref[ndarray]) -> ndarray:
        return matmul(self, other)

    def __neg__(self: Ref[ndarray]) -> ndarray:
        if self.dtype == "bool":
            raise TypeError("The numpy boolean negative, the `-` operator, is not supported, use the `~` "
                            "operator or the logical_not function instead.")
        return ndarray([-v for v in self._data], _copy_shape(self._shape), self.dtype)

    def __invert__(self: Ref[ndarray]) -> ndarray:
        if self.dtype == "float64":
            raise TypeError("ufunc 'invert' not supported for the input types, and the inputs could not "
                            "be safely coerced to any supported types according to the casting rule ''safe''")
        if self.dtype == "bool":
            return ndarray([_bool(v == 0.0) for v in self._data], _copy_shape(self._shape), "bool")
        return ndarray([-v - 1.0 for v in self._data], _copy_shape(self._shape), "int64")

    def __lt__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _LT)

    def __le__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _LE)

    def __gt__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _GT)

    def __ge__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _GE)

    def __eq__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _EQ)

    def __ne__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _NE)

    def __and__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _AND)

    def __or__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _OR)

    def __xor__(self: Ref[ndarray], other: Ref[float | ndarray]) -> ndarray:
        return _binop(self, other, _XOR)

    def sum(self: Ref[ndarray]) -> float:
        return _pairwise_sum(self._data, 0, len(self._data))

    def prod(self: Ref[ndarray]) -> float:
        p: float = 1.0
        for v in self._data:
            p = p * v
        return p

    def mean(self: Ref[ndarray]) -> float:
        return _mean_of(self._data)

    def var(self: Ref[ndarray], ddof: int = 0) -> float:
        return _var_of(self._data, ddof)

    def std(self: Ref[ndarray], ddof: int = 0) -> float:
        return _m_sqrt(_var_of(self._data, ddof))

    def min(self: Ref[ndarray]) -> float:
        return _min_of(self._data)

    def max(self: Ref[ndarray]) -> float:
        return _max_of(self._data)

    def argmin(self: Ref[ndarray]) -> int:
        return _argmin_of(self._data)

    def argmax(self: Ref[ndarray]) -> int:
        return _argmax_of(self._data)

    def all(self: Ref[ndarray]) -> bool:
        for v in self._data:
            if v == 0.0:
                return False
        return True

    def any(self: Ref[ndarray]) -> bool:
        for v in self._data:
            if v != 0.0:
                return True
        return False

    def cumsum(self: Ref[ndarray]) -> ndarray:
        out: list[float] = []
        t: float = 0.0
        for v in self._data:
            t = t + v
            out.append(t)
        dt: str = self.dtype
        if dt == "bool":
            dt = "int64"
        return ndarray(move(out), [len(self._data)], dt)

    def cumprod(self: Ref[ndarray]) -> ndarray:
        out: list[float] = []
        t: float = 1.0
        for v in self._data:
            t = t * v
            out.append(t)
        dt: str = self.dtype
        if dt == "bool":
            dt = "int64"
        return ndarray(move(out), [len(self._data)], dt)

    def dot(self: Ref[ndarray], other: Ref[ndarray]) -> ndarray:
        return dot(self, other)

    def round(self: Ref[ndarray], decimals: int = 0) -> ndarray:
        return around(self, decimals)

    def clip(self: Ref[ndarray], a_min: float, a_max: float) -> ndarray:
        return clip(self, a_min, a_max)

    def sort(self: Mut[ndarray]) -> None:
        s: ndarray = sort(self)
        i: int = 0
        while i < len(self._data):
            self._data[i] = s._data[i]
            i = i + 1

    def argsort(self: Ref[ndarray]) -> ndarray:
        return argsort(self)

    def nonzero(self: Ref[ndarray]) -> ndarray:
        return flatnonzero(self)

    def take(self: Ref[ndarray], indices: Ref[list[int]]) -> ndarray:
        return take(self, indices)


def _pairwise_sum(xs: Ref[list[float]], start: int, n: int) -> float:
    """numpy's pairwise summation (blocks of 8, recursive halving above 128) for bit-parity with `np.sum`."""
    if n < 8:
        res: float = 0.0
        i: int = 0
        while i < n:
            res = res + xs[start + i]
            i = i + 1
        return res
    if n <= 128:
        r0: float = xs[start]
        r1: float = xs[start + 1]
        r2: float = xs[start + 2]
        r3: float = xs[start + 3]
        r4: float = xs[start + 4]
        r5: float = xs[start + 5]
        r6: float = xs[start + 6]
        r7: float = xs[start + 7]
        j: int = 8
        lim: int = n - (n % 8)
        while j < lim:
            r0 = r0 + xs[start + j]
            r1 = r1 + xs[start + j + 1]
            r2 = r2 + xs[start + j + 2]
            r3 = r3 + xs[start + j + 3]
            r4 = r4 + xs[start + j + 4]
            r5 = r5 + xs[start + j + 5]
            r6 = r6 + xs[start + j + 6]
            r7 = r7 + xs[start + j + 7]
            j = j + 8
        res2: float = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7))
        while j < n:
            res2 = res2 + xs[start + j]
            j = j + 1
        return res2
    n2: int = n // 2
    n2 = n2 - (n2 % 8)
    return _pairwise_sum(xs, start, n2) + _pairwise_sum(xs, start + n2, n - n2)


def _mean_of(xs: Ref[list[float]]) -> float:
    """numpy mean: pairwise sum divided by the count (nan for empty input)."""
    if len(xs) == 0:
        return nan
    return _pairwise_sum(xs, 0, len(xs)) / float(len(xs))


def _var_of(xs: Ref[list[float]], ddof: int) -> float:
    """numpy var: mean of squared deviations with `ddof` degrees of freedom."""
    n: int = len(xs)
    if n - ddof <= 0:
        return nan
    m: float = _mean_of(xs)
    sq: list[float] = []
    for v in xs:
        d: float = v - m
        sq.append(d * d)
    return _pairwise_sum(sq, 0, n) / float(n - ddof)


def _min_of(xs: Ref[list[float]]) -> float:
    """Minimum with nan propagation (numpy `min`)."""
    if len(xs) == 0:
        raise ValueError("zero-size array to reduction operation minimum which has no identity")
    m: float = xs[0]
    for v in xs:
        if _m_isnan(v):
            return nan
        if v < m:
            m = v
    return m


def _max_of(xs: Ref[list[float]]) -> float:
    """Maximum with nan propagation (numpy `max`)."""
    if len(xs) == 0:
        raise ValueError("zero-size array to reduction operation maximum which has no identity")
    m: float = xs[0]
    for v in xs:
        if _m_isnan(v):
            return nan
        if v > m:
            m = v
    return m


def _argmin_of(xs: Ref[list[float]]) -> int:
    """Index of the first minimum (first nan wins, as in numpy)."""
    if len(xs) == 0:
        raise ValueError("attempt to get argmin of an empty sequence")
    best: int = 0
    i: int = 0
    while i < len(xs):
        if _m_isnan(xs[i]):
            return i
        if xs[i] < xs[best]:
            best = i
        i = i + 1
    return best


def _argmax_of(xs: Ref[list[float]]) -> int:
    """Index of the first maximum (first nan wins, as in numpy)."""
    if len(xs) == 0:
        raise ValueError("attempt to get argmax of an empty sequence")
    best: int = 0
    i: int = 0
    while i < len(xs):
        if _m_isnan(xs[i]):
            return i
        if xs[i] > xs[best]:
            best = i
        i = i + 1
    return best



def _resolve_shape(shape: Ref[int | tuple[int, int] | list[int]], total: int) -> list[int]:
    """Turn a numpy shape argument (with one optional -1) into a concrete shape list for `total` elements."""
    sh: list[int] = []
    if isinstance(shape, int):
        sh.append(shape)
    if isinstance(shape, tuple):
        sh.append(shape[0])
        sh.append(shape[1])
    if isinstance(shape, list):
        for s in shape:
            sh.append(s)
    if len(sh) == 0 or len(sh) > 2:
        raise ValueError("Coil arrays are 1-D or 2-D")
    known: int = 1
    unknown: int = -1
    i: int = 0
    while i < len(sh):
        if sh[i] == -1:
            if unknown >= 0:
                raise ValueError("can only specify one unknown dimension")
            unknown = i
        elif sh[i] < 0:
            raise ValueError("negative dimensions are not allowed")
        else:
            known = known * sh[i]
        i = i + 1
    if unknown >= 0:
        if known == 0 or total % known != 0:
            raise ValueError("cannot reshape array of size " + str(total) + " into shape " + _shape_compact(sh))
        sh[unknown] = total // known
    if _size_of(sh) != total:
        raise ValueError("cannot reshape array of size " + str(total) + " into shape " + _shape_compact(sh))
    return sh


def _new_shape(shape: Ref[int | tuple[int, int] | list[int]]) -> list[int]:
    """Concrete shape for a fresh array (no -1 allowed)."""
    sh: list[int] = []
    if isinstance(shape, int):
        sh.append(shape)
    if isinstance(shape, tuple):
        sh.append(shape[0])
        sh.append(shape[1])
    if isinstance(shape, list):
        for s in shape:
            sh.append(s)
    if len(sh) == 0 or len(sh) > 2:
        raise ValueError("Coil arrays are 1-D or 2-D")
    for s in sh:
        if s < 0:
            raise ValueError("negative dimensions are not allowed")
    return sh


def _flatten_pyval(v: PyVal, out: Mut[list[float]], shape: Mut[list[int]], depth: int) -> int:
    """Walk a nested Python literal into flat storage; returns the dtype rank seen (0 bool, 1 int, 2 float)."""
    k: str = pyval_kind(v)
    if k == "list":
        n: int = len(v)
        if len(shape) <= depth:
            shape.append(n)
        elif shape[depth] != n:
            seen: list[int] = []
            d: int = 0
            while d < depth:
                seen.append(shape[d])
                d = d + 1
            raise ValueError("setting an array element with a sequence. The requested array has an "
                             "inhomogeneous shape after " + str(depth) + " dimensions. The detected shape was "
                             + _shape_tuple(seen) + " + inhomogeneous part.")
        rank: int = 0
        for item in v:
            r: int = _flatten_pyval(item, out, shape, depth + 1)
            if r > rank:
                rank = r
        return rank
    if k == "bool":
        if v:
            out.append(1.0)
        else:
            out.append(0.0)
        return 0
    if k == "int":
        out.append(float(v))
        return 1
    if k == "float":
        out.append(float(v))
        return 2
    raise TypeError("Coil arrays hold numbers only, got " + k)


def array(obj: PyVal, dtype: str = "") -> ndarray:
    """numpy.array: build an array from a (nested) list of numbers."""
    out: list[float] = []
    shape: list[int] = []
    rank: int = _flatten_pyval(obj, out, shape, 0)
    if len(shape) == 0:
        raise TypeError("Coil arrays need a list of numbers (0-d arrays are not supported)")
    if len(shape) > 2:
        raise ValueError("Coil arrays are 1-D or 2-D")
    dt: str = "float64"
    if dtype != "":
        dt = _norm_dtype(dtype)
    elif rank == 1:
        dt = "int64"
    elif rank == 0:
        dt = "bool"
    if dt != "float64":
        i: int = 0
        while i < len(out):
            out[i] = _cast(out[i], dt)
            i = i + 1
    return ndarray(move(out), move(shape), dt)


def asarray(obj: PyVal, dtype: str = "") -> ndarray:
    """numpy.asarray (always copies here)."""
    return array(obj, dtype)


def full(shape: Ref[int | tuple[int, int] | list[int]], fill_value: float, dtype: str = "") -> ndarray:
    """numpy.full."""
    sh: list[int] = _new_shape(shape)
    dt: str = _norm_dtype(dtype)
    v: float = _cast(fill_value, dt)
    n: int = _size_of(sh)
    out: list[float] = []
    i: int = 0
    while i < n:
        out.append(v)
        i = i + 1
    return ndarray(move(out), move(sh), dt)


def zeros(shape: Ref[int | tuple[int, int] | list[int]], dtype: str = "") -> ndarray:
    """numpy.zeros."""
    return full(shape, 0.0, dtype)


def ones(shape: Ref[int | tuple[int, int] | list[int]], dtype: str = "") -> ndarray:
    """numpy.ones."""
    return full(shape, 1.0, dtype)


def empty(shape: Ref[int | tuple[int, int] | list[int]], dtype: str = "") -> ndarray:
    """numpy.empty (zero-filled here)."""
    return full(shape, 0.0, dtype)


def zeros_like(a: Ref[ndarray], dtype: str = "") -> ndarray:
    """numpy.zeros_like."""
    dt: str = a.dtype
    if dtype != "":
        dt = _norm_dtype(dtype)
    return full(_copy_shape(a._shape), 0.0, dt)


def ones_like(a: Ref[ndarray], dtype: str = "") -> ndarray:
    """numpy.ones_like."""
    dt: str = a.dtype
    if dtype != "":
        dt = _norm_dtype(dtype)
    return full(_copy_shape(a._shape), 1.0, dt)


def full_like(a: Ref[ndarray], fill_value: float, dtype: str = "") -> ndarray:
    """numpy.full_like."""
    dt: str = a.dtype
    if dtype != "":
        dt = _norm_dtype(dtype)
    return full(_copy_shape(a._shape), fill_value, dt)


def empty_like(a: Ref[ndarray], dtype: str = "") -> ndarray:
    """numpy.empty_like (zero-filled here)."""
    return zeros_like(a, dtype)


def _is_integral(x: float) -> bool:
    """Whether a finite float has no fractional part."""
    if _m_isnan(x) or _m_isinf(x):
        return False
    return x == float(_m_trunc(x))


def arange(start: float, stop: float | None = None, step: float = 1.0, dtype: str = "") -> ndarray:
    """numpy.arange: integral arguments give int64, anything else float64."""
    lo: float = 0.0
    hi: float = start
    if stop is not None:
        lo = start
        hi = stop
    if step == 0.0:
        raise ZeroDivisionError("division by zero")
    span: float = (hi - lo) / step
    n: int = 0
    if span > 0.0:
        n = _m_ceil(span)
    out: list[float] = []
    i: int = 0
    while i < n:
        out.append(lo + float(i) * step)
        i = i + 1
    dt: str = "float64"
    if dtype != "":
        dt = _norm_dtype(dtype)
    elif _is_integral(lo) and _is_integral(hi) and _is_integral(step):
        dt = "int64"
    if dt != "float64":
        j: int = 0
        while j < len(out):
            out[j] = _cast(out[j], dt)
            j = j + 1
    return ndarray(move(out), [n], dt)


def linspace(start: float, stop: float, num: int = 50, endpoint: bool = True) -> ndarray:
    """numpy.linspace (float64)."""
    if num < 0:
        raise ValueError("Number of samples, " + str(num) + ", must be non-negative.")
    div: int = num
    if endpoint:
        div = num - 1
    delta: float = stop - start
    out: list[float] = []
    i: int = 0
    if div > 0:
        step: float = delta / float(div)
        while i < num:
            if step == 0.0:
                out.append(float(i) / float(div) * delta + start)
            else:
                out.append(float(i) * step + start)
            i = i + 1
    else:
        while i < num:
            out.append(float(i) * delta + start)
            i = i + 1
    if endpoint and num > 1:
        out[num - 1] = stop
    return ndarray(move(out), [num], "float64")


def eye(n: int, m: int | None = None, k: int = 0, dtype: str = "") -> ndarray:
    """numpy.eye: 2-D array with ones on the k-th diagonal."""
    cols: int = n
    if m is not None:
        cols = m
    a: ndarray = zeros([n, cols], dtype)
    r: int = 0
    while r < n:
        c: int = r + k
        if c >= 0 and c < cols:
            a._data[r * cols + c] = 1.0
        r = r + 1
    return a


def identity(n: int, dtype: str = "") -> ndarray:
    """numpy.identity."""
    return eye(n, None, 0, dtype)


def copy(a: Ref[ndarray]) -> ndarray:
    """numpy.copy."""
    return a.copy()


def _broadcast_shape(sa: Ref[list[int]], sb: Ref[list[int]]) -> list[int]:
    """numpy broadcasting of two shapes (up to 2-D) or ValueError."""
    nd: int = len(sa)
    if len(sb) > nd:
        nd = len(sb)
    out: list[int] = []
    i: int = 0
    while i < nd:
        da: int = 1
        db: int = 1
        ia: int = i - (nd - len(sa))
        ib: int = i - (nd - len(sb))
        if ia >= 0:
            da = sa[ia]
        if ib >= 0:
            db = sb[ib]
        if da == db or db == 1:
            out.append(da)
        elif da == 1:
            out.append(db)
        else:
            raise ValueError("operands could not be broadcast together with shapes "
                             + _shape_compact(sa) + " " + _shape_compact(sb) + " ")
        i = i + 1
    return out


def _src_index(shape: Ref[list[int]], out_shape: Ref[list[int]], flat: int) -> int:
    """Flat index into an operand of `shape` for position `flat` of the broadcast `out_shape`."""
    nd: int = len(out_shape)
    if len(shape) == nd and _same_shape(shape, out_shape):
        return flat
    r: int = 0
    c: int = flat
    if nd == 2:
        r = flat // out_shape[1]
        c = flat % out_shape[1]
    if len(shape) == 1:
        if shape[0] == 1:
            return 0
        return c
    sr: int = r
    sc: int = c
    if shape[0] == 1:
        sr = 0
    if shape[1] == 1:
        sc = 0
    return sr * shape[1] + sc


def _result_dtype(da: str, db: str) -> str:
    """numpy-style promotion across the three storage dtypes."""
    if da == "float64" or db == "float64":
        return "float64"
    if da == "int64" or db == "int64":
        return "int64"
    return "bool"


def _scalar_dtype(da: str, k: float) -> str:
    """Promotion of an array dtype against a Python scalar (integral scalars keep int64)."""
    if da == "float64":
        return "float64"
    if _is_integral(k):
        return "int64"
    return "float64"


_ADD: int = 0
_SUB: int = 1
_MUL: int = 2
_DIV: int = 3
_FLOORDIV: int = 4
_MOD: int = 5
_POW: int = 6
_LT: int = 7
_LE: int = 8
_GT: int = 9
_GE: int = 10
_EQ: int = 11
_NE: int = 12
_AND: int = 13
_OR: int = 14
_XOR: int = 15
_MAX: int = 16
_MIN: int = 17
_LAND: int = 18
_LOR: int = 19
_LXOR: int = 20
_ATAN2: int = 21
_HYPOT: int = 22


def _bool(b: bool) -> float:
    """Store a bool as 1.0/0.0."""
    if b:
        return 1.0
    return 0.0


def _bit_op(x: int, y: int, op: int) -> int:
    """64-bit two's-complement and/or/xor built bit by bit (the subset has no bitwise operators)."""
    r: int = 0
    weight: int = 1
    a: int = x
    b: int = y
    i: int = 0
    while i < 64:
        ba: int = a % 2
        bb: int = b % 2
        bit: int = 0
        if op == _AND:
            if ba == 1 and bb == 1:
                bit = 1
        elif op == _OR:
            if ba == 1 or bb == 1:
                bit = 1
        else:
            if ba != bb:
                bit = 1
        if bit == 1:
            if i == 63:
                r = r - 4611686018427387904 - 4611686018427387904
            else:
                r = r + weight
        if i < 62:
            weight = weight * 2
        a = a // 2
        b = b // 2
        i = i + 1
    return r


def _scalar_op(x: float, y: float, op: int, int_mode: bool) -> float:
    """Apply one binary ufunc to two stored values with numpy's float/int edge rules."""
    if op == _ADD:
        return x + y
    if op == _SUB:
        return x - y
    if op == _MUL:
        return x * y
    if op == _DIV:
        if y == 0.0:
            if _m_isnan(x) or x == 0.0:
                return nan
            if (x > 0.0) == (str(y)[0] != "-"):
                return inf
            return -inf
        return x / y
    if op == _FLOORDIV:
        if y == 0.0:
            if int_mode:
                return 0.0
            if _m_isnan(x) or x == 0.0:
                return nan
            if (x > 0.0) == (str(y)[0] != "-"):
                return inf
            return -inf
        if _m_isinf(x) or _m_isnan(x) or _m_isnan(y):
            return nan
        if _m_isinf(y):
            if x == 0.0:
                return 0.0
            if (x > 0.0) == (y > 0.0):
                return 0.0
            return -1.0
        return float(_m_floor(x / y)) if _m_fabs(x / y) < 4503599627370496.0 else x / y
    if op == _MOD:
        if y == 0.0:
            if int_mode:
                return 0.0
            return nan
        if _m_isinf(x) or _m_isnan(x) or _m_isnan(y):
            return nan
        if _m_isinf(y):
            if x == 0.0 or (x > 0.0) == (y > 0.0):
                return x
            return y
        return x % y
    if op == _POW:
        if int_mode and y < 0.0:
            raise ValueError("Integers to negative integer powers are not allowed.")
        if x == 0.0 and y < 0.0:
            return inf
        if x < 0.0 and not _is_integral(y) and not _m_isinf(y):
            return nan
        if x == 0.0 and _m_isnan(y):
            return nan
        if _m_fabs(x) == 1.0 and _m_isinf(y):
            return 1.0
        if x == 1.0:
            return 1.0
        if y == 0.0:
            return 1.0
        return x ** y
    if op == _LT:
        return _bool(x < y)
    if op == _LE:
        return _bool(x <= y)
    if op == _GT:
        return _bool(x > y)
    if op == _GE:
        return _bool(x >= y)
    if op == _EQ:
        return _bool(x == y)
    if op == _NE:
        return _bool(x != y)
    if op == _AND or op == _OR or op == _XOR:
        return float(_bit_op(int(x), int(y), op))
    if op == _MAX:
        if _m_isnan(x) or _m_isnan(y):
            return nan
        if x >= y:
            return x
        return y
    if op == _MIN:
        if _m_isnan(x) or _m_isnan(y):
            return nan
        if x <= y:
            return x
        return y
    if op == _LAND:
        return _bool(x != 0.0 and y != 0.0)
    if op == _LOR:
        return _bool(x != 0.0 or y != 0.0)
    if op == _LXOR:
        return _bool((x != 0.0) != (y != 0.0))
    if op == _ATAN2:
        return _m_atan2(x, y)
    return _m_sqrt(x * x + y * y)


def _op_dtype(op: int, da: str, db: str) -> str:
    """Result dtype of a binary ufunc given the (already promoted) operand dtypes."""
    if op >= _LT and op <= _NE:
        return "bool"
    if op >= _LAND and op <= _LXOR:
        return "bool"
    if op == _AND or op == _OR or op == _XOR:
        if da == "float64" or db == "float64":
            raise TypeError("ufunc 'bitwise_and' not supported for the input types, and the inputs could "
                            "not be safely coerced to any supported types according to the casting rule "
                            "''safe''")
        return _result_dtype(da, db)
    if op == _DIV or op == _ATAN2 or op == _HYPOT:
        return "float64"
    dt: str = _result_dtype(da, db)
    if dt == "bool":
        if op == _SUB:
            raise TypeError("numpy boolean subtract, the `-` operator, is not supported, use the "
                            "bitwise_xor, the `^` operator, or the logical_xor function instead.")
        if op == _ADD or op == _MUL or op == _MAX or op == _MIN:
            return "bool"
        return "int64"
    return dt


def _apply2(a: Ref[ndarray], b: Ref[ndarray], op: int) -> ndarray:
    """Elementwise binary ufunc over two arrays with broadcasting."""
    sh: list[int] = _broadcast_shape(a._shape, b._shape)
    dt: str = _op_dtype(op, a.dtype, b.dtype)
    int_mode: bool = a.dtype != "float64" and b.dtype != "float64"
    n: int = _size_of(sh)
    out: list[float] = []
    i: int = 0
    while i < n:
        x: float = a._data[_src_index(a._shape, sh, i)]
        y: float = b._data[_src_index(b._shape, sh, i)]
        out.append(_cast(_scalar_op(x, y, op, int_mode), dt))
        i = i + 1
    return ndarray(move(out), move(sh), dt)


def _apply2s(a: Ref[ndarray], k: float, op: int, reversed_: bool) -> ndarray:
    """Elementwise binary ufunc between an array and a scalar (scalar on the right unless reversed)."""
    kd: str = _scalar_dtype(a.dtype, k)
    if a.dtype == "bool" and (k == 0.0 or k == 1.0) and (op == _AND or op == _OR or op == _XOR
                                                          or op == _LAND or op == _LOR or op == _LXOR):
        kd = "bool"
    dt: str = _op_dtype(op, a.dtype, kd)
    int_mode: bool = a.dtype != "float64" and kd != "float64"
    out: list[float] = []
    for v in a._data:
        if reversed_:
            out.append(_cast(_scalar_op(k, v, op, int_mode), dt))
        else:
            out.append(_cast(_scalar_op(v, k, op, int_mode), dt))
    return ndarray(move(out), _copy_shape(a._shape), dt)


def _binop(a: Ref[ndarray], other: Ref[float | ndarray], op: int) -> ndarray:
    """Dispatch an operator on an array against an array-or-scalar right operand."""
    if isinstance(other, ndarray):
        return _apply2(a, other, op)
    return _apply2s(a, float(other), op, False)


def _binop_r(a: Ref[ndarray], other: Ref[float | ndarray], op: int) -> ndarray:
    """Dispatch with the operands swapped (array on the right)."""
    if isinstance(other, ndarray):
        return _apply2(other, a, op)
    return _apply2s(a, float(other), op, True)



def sum(a: Ref[ndarray]) -> float:
    """numpy.sum over the whole array (see `sum_axis` for axis reductions)."""
    return a.sum()


def prod(a: Ref[ndarray]) -> float:
    """numpy.prod over the whole array."""
    return a.prod()


def mean(a: Ref[ndarray]) -> float:
    """numpy.mean over the whole array."""
    return a.mean()


def average(a: Ref[ndarray], weights: Owned[ndarray | None] = None) -> float:
    """numpy.average, optionally weighted."""
    if weights is None:
        return a.mean()
    if len(weights._data) != len(a._data):
        raise ValueError("Length of weights not compatible with specified axis.")
    num: list[float] = []
    i: int = 0
    while i < len(a._data):
        num.append(a._data[i] * weights._data[i])
        i = i + 1
    wsum: float = _pairwise_sum(weights._data, 0, len(weights._data))
    if wsum == 0.0:
        raise ZeroDivisionError("Weights sum to zero, can't be normalized")
    return _pairwise_sum(num, 0, len(num)) / wsum


def var(a: Ref[ndarray], ddof: int = 0) -> float:
    """numpy.var over the whole array."""
    return a.var(ddof)


def std(a: Ref[ndarray], ddof: int = 0) -> float:
    """numpy.std over the whole array."""
    return a.std(ddof)


def min(a: Ref[ndarray]) -> float:
    """numpy.min over the whole array."""
    return a.min()


def max(a: Ref[ndarray]) -> float:
    """numpy.max over the whole array."""
    return a.max()


def amin(a: Ref[ndarray]) -> float:
    """numpy.amin."""
    return a.min()


def amax(a: Ref[ndarray]) -> float:
    """numpy.amax."""
    return a.max()


def ptp(a: Ref[ndarray]) -> float:
    """numpy.ptp: max - min."""
    return a.max() - a.min()


def argmin(a: Ref[ndarray]) -> int:
    """numpy.argmin (flat index)."""
    return a.argmin()


def argmax(a: Ref[ndarray]) -> int:
    """numpy.argmax (flat index)."""
    return a.argmax()


def all(a: Ref[ndarray]) -> bool:
    """numpy.all."""
    return a.all()


def any(a: Ref[ndarray]) -> bool:
    """numpy.any."""
    return a.any()


def cumsum(a: Ref[ndarray]) -> ndarray:
    """numpy.cumsum over the flattened array."""
    return a.cumsum()


def cumprod(a: Ref[ndarray]) -> ndarray:
    """numpy.cumprod over the flattened array."""
    return a.cumprod()


def count_nonzero(a: Ref[ndarray]) -> int:
    """numpy.count_nonzero."""
    n: int = 0
    for v in a._data:
        if v != 0.0:
            n = n + 1
    return n


def flatnonzero(a: Ref[ndarray]) -> ndarray:
    """numpy.flatnonzero: flat indices of the non-zero elements."""
    out: list[float] = []
    i: int = 0
    while i < len(a._data):
        if a._data[i] != 0.0:
            out.append(float(i))
        i = i + 1
    n_out: int = len(out)
    return ndarray(move(out), [n_out], "int64")


def median(a: Ref[ndarray]) -> float:
    """numpy.median (nan if any element is nan)."""
    n: int = len(a._data)
    if n == 0:
        return nan
    for v in a._data:
        if _m_isnan(v):
            return nan
    s: list[float] = sorted(a._data)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def percentile(a: Ref[ndarray], q: float) -> float:
    """numpy.percentile with the default linear interpolation."""
    return quantile(a, q / 100.0)


def quantile(a: Ref[ndarray], q: float) -> float:
    """numpy.quantile with the default linear interpolation."""
    if q < 0.0 or q > 1.0:
        raise ValueError("Quantiles must be in the range [0, 1]")
    n: int = len(a._data)
    if n == 0:
        return nan
    for v in a._data:
        if _m_isnan(v):
            return nan
    s: list[float] = sorted(a._data)
    pos: float = q * float(n - 1)
    lo: int = _m_floor(pos)
    hi: int = lo
    if lo + 1 < n:
        hi = lo + 1
    g: float = pos - float(lo)
    return s[lo] + (s[hi] - s[lo]) * g


def _rows(a: Ref[ndarray]) -> int:
    """Row count of a 2-D array (a 1-D array is one row)."""
    if len(a._shape) == 1:
        return 1
    return a._shape[0]


def _cols(a: Ref[ndarray]) -> int:
    """Column count (length for 1-D)."""
    if len(a._shape) == 1:
        return a._shape[0]
    return a._shape[1]


def _lanes(a: Ref[ndarray], axis: int) -> list[list[float]]:
    """Split a 2-D array into the 1-D lanes reduced by `axis` (axis 0 → columns, axis 1 → rows)."""
    if len(a._shape) != 2:
        raise ValueError("axis reductions need a 2-D array (use the plain reduction for 1-D)")
    ax: int = axis
    if ax < 0:
        ax = ax + 2
    if ax != 0 and ax != 1:
        raise ValueError("axis " + str(axis) + " is out of bounds for array of dimension 2")
    rows: int = a._shape[0]
    cols: int = a._shape[1]
    lanes: list[list[float]] = []
    if ax == 1:
        r: int = 0
        while r < rows:
            lane: list[float] = []
            c: int = 0
            while c < cols:
                lane.append(a._data[r * cols + c])
                c = c + 1
            lanes.append(move(lane))
            r = r + 1
        return lanes
    c2: int = 0
    while c2 < cols:
        lane2: list[float] = []
        r2: int = 0
        while r2 < rows:
            lane2.append(a._data[r2 * cols + c2])
            r2 = r2 + 1
        lanes.append(move(lane2))
        c2 = c2 + 1
    return lanes


def _plain_sum(xs: Ref[list[float]]) -> float:
    """Sequential sum (numpy reduces along axis 0 without pairwise blocking)."""
    t: float = 0.0
    for v in xs:
        t = t + v
    return t


def sum_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.sum(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        if axis == 0 or axis == -2:
            out.append(_plain_sum(lane))
        else:
            out.append(_pairwise_sum(lane, 0, len(lane)))
    dt: str = a.dtype
    if dt == "bool":
        dt = "int64"
    return ndarray(move(out), [len(lanes)], dt)


def mean_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.mean(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        if axis == 0 or axis == -2:
            out.append(_plain_sum(lane) / float(len(lane)))
        else:
            out.append(_mean_of(lane))
    return ndarray(move(out), [len(lanes)], "float64")


def var_axis(a: Ref[ndarray], axis: int, ddof: int = 0) -> ndarray:
    """`numpy.var(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        out.append(_var_of(lane, ddof))
    return ndarray(move(out), [len(lanes)], "float64")


def std_axis(a: Ref[ndarray], axis: int, ddof: int = 0) -> ndarray:
    """`numpy.std(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        out.append(_m_sqrt(_var_of(lane, ddof)))
    return ndarray(move(out), [len(lanes)], "float64")


def prod_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.prod(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        p: float = 1.0
        for v in lane:
            p = p * v
        out.append(p)
    dt: str = a.dtype
    if dt == "bool":
        dt = "int64"
    return ndarray(move(out), [len(lanes)], dt)


def min_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.min(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        out.append(_min_of(lane))
    return ndarray(move(out), [len(lanes)], a.dtype)


def max_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.max(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        out.append(_max_of(lane))
    return ndarray(move(out), [len(lanes)], a.dtype)


def argmin_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.argmin(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        out.append(float(_argmin_of(lane)))
    return ndarray(move(out), [len(lanes)], "int64")


def argmax_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.argmax(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        out.append(float(_argmax_of(lane)))
    return ndarray(move(out), [len(lanes)], "int64")


def all_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.all(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        ok: bool = True
        for v in lane:
            if v == 0.0:
                ok = False
        out.append(_bool(ok))
    return ndarray(move(out), [len(lanes)], "bool")


def any_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.any(a, axis=axis)` for 2-D arrays."""
    lanes: list[list[float]] = _lanes(a, axis)
    out: list[float] = []
    for lane in lanes:
        hit: bool = False
        for v in lane:
            if v != 0.0:
                hit = True
        out.append(_bool(hit))
    return ndarray(move(out), [len(lanes)], "bool")


def cumsum_axis(a: Ref[ndarray], axis: int) -> ndarray:
    """`numpy.cumsum(a, axis=axis)` for 2-D arrays (result keeps the 2-D shape)."""
    lanes: list[list[float]] = _lanes(a, axis)
    rows: int = a._shape[0]
    cols: int = a._shape[1]
    out: list[float] = []
    n: int = rows * cols
    i: int = 0
    while i < n:
        out.append(0.0)
        i = i + 1
    li: int = 0
    for lane in lanes:
        t: float = 0.0
        k: int = 0
        while k < len(lane):
            t = t + lane[k]
            if axis == 0 or axis == -2:
                out[k * cols + li] = t
            else:
                out[li * cols + k] = t
            k = k + 1
        li = li + 1
    dt: str = a.dtype
    if dt == "bool":
        dt = "int64"
    return ndarray(move(out), [rows, cols], dt)


def _map(a: Ref[ndarray], fn: int) -> ndarray:
    """Apply a unary float ufunc (by code) elementwise, producing float64."""
    out: list[float] = []
    for v in a._data:
        out.append(_unary(v, fn))
    return ndarray(move(out), _copy_shape(a._shape), "float64")


_U_SQRT: int = 0
_U_EXP: int = 1
_U_LOG: int = 2
_U_LOG2: int = 3
_U_LOG10: int = 4
_U_SIN: int = 5
_U_COS: int = 6
_U_TAN: int = 7
_U_ASIN: int = 8
_U_ACOS: int = 9
_U_ATAN: int = 10
_U_SINH: int = 11
_U_COSH: int = 12
_U_TANH: int = 13
_U_FLOOR: int = 14
_U_CEIL: int = 15
_U_TRUNC: int = 16
_U_RINT: int = 17
_U_EXP2: int = 18
_U_EXPM1: int = 19
_U_LOG1P: int = 20
_U_CBRT: int = 21
_U_SQUARE: int = 22
_U_RECIP: int = 23
_U_DEG: int = 24
_U_RAD: int = 25
_U_ABS: int = 26


def _unary(x: float, fn: int) -> float:
    """One unary ufunc on a float with numpy's domain behaviour (nan/inf instead of exceptions)."""
    if fn == _U_SQRT:
        if x < 0.0:
            return nan
        return _m_sqrt(x)
    if fn == _U_EXP:
        if x > 709.782712893384:
            return inf
        return _m_exp(x)
    if fn == _U_LOG or fn == _U_LOG2 or fn == _U_LOG10:
        if _m_isnan(x) or x < 0.0:
            return nan
        if x == 0.0:
            return -inf
        if _m_isinf(x):
            return inf
        if fn == _U_LOG:
            return _m_log(x)
        if fn == _U_LOG2:
            return _m_log2(x)
        return _m_log10(x)
    if fn == _U_SIN:
        if _m_isinf(x):
            return nan
        return _m_sin(x)
    if fn == _U_COS:
        if _m_isinf(x):
            return nan
        return _m_cos(x)
    if fn == _U_TAN:
        if _m_isinf(x):
            return nan
        return _m_tan(x)
    if fn == _U_ASIN:
        if x < -1.0 or x > 1.0:
            return nan
        return _m_asin(x)
    if fn == _U_ACOS:
        if x < -1.0 or x > 1.0:
            return nan
        return _m_acos(x)
    if fn == _U_ATAN:
        return _m_atan(x)
    if fn == _U_SINH:
        if x > 710.4758600739439:
            return inf
        if x < -710.4758600739439:
            return -inf
        return _m_sinh(x)
    if fn == _U_COSH:
        if x > 710.4758600739439 or x < -710.4758600739439:
            return inf
        return _m_cosh(x)
    if fn == _U_TANH:
        return _m_tanh(x)
    if fn == _U_FLOOR:
        if _m_isnan(x) or _m_isinf(x) or _m_fabs(x) >= 4503599627370496.0:
            return x
        return float(_m_floor(x))
    if fn == _U_CEIL:
        if _m_isnan(x) or _m_isinf(x) or _m_fabs(x) >= 4503599627370496.0:
            return x
        return float(_m_ceil(x))
    if fn == _U_TRUNC:
        if _m_isnan(x) or _m_isinf(x) or _m_fabs(x) >= 4503599627370496.0:
            return x
        return float(_m_trunc(x))
    if fn == _U_RINT:
        return _rint(x)
    if fn == _U_EXP2:
        if x > 1024.0:
            return inf
        return _m_exp2(x)
    if fn == _U_EXPM1:
        if x > 709.782712893384:
            return inf
        return _m_expm1(x)
    if fn == _U_LOG1P:
        if _m_isnan(x) or x < -1.0:
            return nan
        if x == -1.0:
            return -inf
        if _m_isinf(x):
            return inf
        return _m_log1p(x)
    if fn == _U_CBRT:
        return _m_cbrt(x)
    if fn == _U_SQUARE:
        return x * x
    if fn == _U_RECIP:
        if x == 0.0:
            return inf
        return 1.0 / x
    if fn == _U_DEG:
        return x * 180.0 / pi
    if fn == _U_RAD:
        return x * pi / 180.0
    return _m_fabs(x)


def sqrt(a: Ref[ndarray]) -> ndarray:
    """numpy.sqrt (nan for negative input)."""
    return _map(a, _U_SQRT)


def cbrt(a: Ref[ndarray]) -> ndarray:
    """numpy.cbrt."""
    return _map(a, _U_CBRT)


def exp(a: Ref[ndarray]) -> ndarray:
    """numpy.exp."""
    return _map(a, _U_EXP)


def exp2(a: Ref[ndarray]) -> ndarray:
    """numpy.exp2."""
    return _map(a, _U_EXP2)


def expm1(a: Ref[ndarray]) -> ndarray:
    """numpy.expm1."""
    return _map(a, _U_EXPM1)


def log(a: Ref[ndarray]) -> ndarray:
    """numpy.log (nan/-inf outside the domain)."""
    return _map(a, _U_LOG)


def log2(a: Ref[ndarray]) -> ndarray:
    """numpy.log2."""
    return _map(a, _U_LOG2)


def log10(a: Ref[ndarray]) -> ndarray:
    """numpy.log10."""
    return _map(a, _U_LOG10)


def log1p(a: Ref[ndarray]) -> ndarray:
    """numpy.log1p."""
    return _map(a, _U_LOG1P)


def sin(a: Ref[ndarray]) -> ndarray:
    """numpy.sin."""
    return _map(a, _U_SIN)


def cos(a: Ref[ndarray]) -> ndarray:
    """numpy.cos."""
    return _map(a, _U_COS)


def tan(a: Ref[ndarray]) -> ndarray:
    """numpy.tan."""
    return _map(a, _U_TAN)


def arcsin(a: Ref[ndarray]) -> ndarray:
    """numpy.arcsin."""
    return _map(a, _U_ASIN)


def arccos(a: Ref[ndarray]) -> ndarray:
    """numpy.arccos."""
    return _map(a, _U_ACOS)


def arctan(a: Ref[ndarray]) -> ndarray:
    """numpy.arctan."""
    return _map(a, _U_ATAN)


def sinh(a: Ref[ndarray]) -> ndarray:
    """numpy.sinh."""
    return _map(a, _U_SINH)


def cosh(a: Ref[ndarray]) -> ndarray:
    """numpy.cosh."""
    return _map(a, _U_COSH)


def tanh(a: Ref[ndarray]) -> ndarray:
    """numpy.tanh."""
    return _map(a, _U_TANH)


def abs(a: Ref[ndarray]) -> ndarray:
    """numpy.abs (keeps the dtype)."""
    if a.dtype == "float64":
        return _map(a, _U_ABS)
    out: list[float] = []
    for v in a._data:
        out.append(_m_fabs(v))
    return ndarray(move(out), _copy_shape(a._shape), a.dtype)


def absolute(a: Ref[ndarray]) -> ndarray:
    """numpy.absolute."""
    return abs(a)


def fabs(a: Ref[ndarray]) -> ndarray:
    """numpy.fabs (always float64)."""
    return _map(a, _U_ABS)


def negative(a: Ref[ndarray]) -> ndarray:
    """numpy.negative."""
    return -a


def sign(a: Ref[ndarray]) -> ndarray:
    """numpy.sign (keeps the dtype; nan stays nan)."""
    out: list[float] = []
    for v in a._data:
        if _m_isnan(v):
            out.append(nan)
        elif v > 0.0:
            out.append(1.0)
        elif v < 0.0:
            out.append(-1.0)
        else:
            out.append(0.0)
    dt: str = a.dtype
    if dt == "bool":
        dt = "int64"
    return ndarray(move(out), _copy_shape(a._shape), dt)


def square(a: Ref[ndarray]) -> ndarray:
    """numpy.square (keeps the dtype)."""
    return a * a


def reciprocal(a: Ref[ndarray]) -> ndarray:
    """numpy.reciprocal (float64)."""
    return _map(a, _U_RECIP)


def floor(a: Ref[ndarray]) -> ndarray:
    """numpy.floor (float64)."""
    return _map(a, _U_FLOOR)


def ceil(a: Ref[ndarray]) -> ndarray:
    """numpy.ceil (float64)."""
    return _map(a, _U_CEIL)


def trunc(a: Ref[ndarray]) -> ndarray:
    """numpy.trunc (float64)."""
    return _map(a, _U_TRUNC)


def rint(a: Ref[ndarray]) -> ndarray:
    """numpy.rint: round half to even."""
    return _map(a, _U_RINT)


def fix(a: Ref[ndarray]) -> ndarray:
    """numpy.fix: round toward zero."""
    return _map(a, _U_TRUNC)


def around(a: Ref[ndarray], decimals: int = 0) -> ndarray:
    """numpy.around / numpy.round: scale, rint, unscale (numpy's algorithm)."""
    if a.dtype != "float64":
        if decimals >= 0:
            return a.copy()
        f: float = 10.0 ** float(-decimals)
        out0: list[float] = []
        for v in a._data:
            out0.append(_rint(v / f) * f)
        return ndarray(move(out0), _copy_shape(a._shape), a.dtype)
    out: list[float] = []
    if decimals == 0:
        for v in a._data:
            out.append(_rint(v))
    elif decimals > 0:
        scale: float = 10.0 ** float(decimals)
        for v in a._data:
            out.append(_rint(v * scale) / scale)
    else:
        scale2: float = 10.0 ** float(-decimals)
        for v in a._data:
            out.append(_rint(v / scale2) * scale2)
    return ndarray(move(out), _copy_shape(a._shape), "float64")


def round(a: Ref[ndarray], decimals: int = 0) -> ndarray:
    """numpy.round."""
    return around(a, decimals)


def round_(a: Ref[ndarray], decimals: int = 0) -> ndarray:
    """numpy.round_."""
    return around(a, decimals)


def degrees(a: Ref[ndarray]) -> ndarray:
    """numpy.degrees."""
    return _map(a, _U_DEG)


def radians(a: Ref[ndarray]) -> ndarray:
    """numpy.radians."""
    return _map(a, _U_RAD)


def rad2deg(a: Ref[ndarray]) -> ndarray:
    """numpy.rad2deg."""
    return _map(a, _U_DEG)


def deg2rad(a: Ref[ndarray]) -> ndarray:
    """numpy.deg2rad."""
    return _map(a, _U_RAD)


def isnan(a: Ref[ndarray]) -> ndarray:
    """numpy.isnan."""
    return ndarray([_bool(_m_isnan(v)) for v in a._data], _copy_shape(a._shape), "bool")


def isinf(a: Ref[ndarray]) -> ndarray:
    """numpy.isinf."""
    return ndarray([_bool(_m_isinf(v)) for v in a._data], _copy_shape(a._shape), "bool")


def isfinite(a: Ref[ndarray]) -> ndarray:
    """numpy.isfinite."""
    return ndarray([_bool(not _m_isnan(v) and not _m_isinf(v)) for v in a._data], _copy_shape(a._shape), "bool")


def nan_to_num(a: Ref[ndarray], nan_: float = 0.0, posinf: float = 1.7976931348623157e308,
               neginf: float = -1.7976931348623157e308) -> ndarray:
    """numpy.nan_to_num."""
    out: list[float] = []
    for v in a._data:
        if _m_isnan(v):
            out.append(nan_)
        elif _m_isinf(v):
            if v > 0.0:
                out.append(posinf)
            else:
                out.append(neginf)
        else:
            out.append(v)
    return ndarray(move(out), _copy_shape(a._shape), a.dtype)



def add(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.add."""
    return _binop(a, b, _ADD)


def subtract(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.subtract."""
    return _binop(a, b, _SUB)


def multiply(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.multiply."""
    return _binop(a, b, _MUL)


def divide(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.divide."""
    return _binop(a, b, _DIV)


def true_divide(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.true_divide."""
    return _binop(a, b, _DIV)


def floor_divide(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.floor_divide."""
    return _binop(a, b, _FLOORDIV)


def mod(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.mod."""
    return _binop(a, b, _MOD)


def remainder(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.remainder."""
    return _binop(a, b, _MOD)


def power(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.power."""
    return _binop(a, b, _POW)


def maximum(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.maximum (nan-propagating)."""
    return _binop(a, b, _MAX)


def minimum(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.minimum (nan-propagating)."""
    return _binop(a, b, _MIN)


def arctan2(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.arctan2."""
    return _binop(a, b, _ATAN2)


def hypot(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.hypot."""
    return _binop(a, b, _HYPOT)


def equal(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.equal."""
    return _binop(a, b, _EQ)


def not_equal(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.not_equal."""
    return _binop(a, b, _NE)


def less(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.less."""
    return _binop(a, b, _LT)


def less_equal(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.less_equal."""
    return _binop(a, b, _LE)


def greater(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.greater."""
    return _binop(a, b, _GT)


def greater_equal(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.greater_equal."""
    return _binop(a, b, _GE)


def logical_and(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.logical_and."""
    return _binop(a, b, _LAND)


def logical_or(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.logical_or."""
    return _binop(a, b, _LOR)


def logical_xor(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.logical_xor."""
    return _binop(a, b, _LXOR)


def logical_not(a: Ref[ndarray]) -> ndarray:
    """numpy.logical_not."""
    return ndarray([_bool(v == 0.0) for v in a._data], _copy_shape(a._shape), "bool")


def bitwise_and(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.bitwise_and."""
    return _binop(a, b, _AND)


def bitwise_or(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.bitwise_or."""
    return _binop(a, b, _OR)


def bitwise_xor(a: Ref[ndarray], b: Ref[float | ndarray]) -> ndarray:
    """numpy.bitwise_xor."""
    return _binop(a, b, _XOR)


def invert(a: Ref[ndarray]) -> ndarray:
    """numpy.invert."""
    return ~a


def clip(a: Ref[ndarray], a_min: float, a_max: float) -> ndarray:
    """numpy.clip with scalar bounds."""
    out: list[float] = []
    for v in a._data:
        if _m_isnan(v):
            out.append(v)
        elif v < a_min:
            out.append(_cast(a_min, a.dtype))
        elif v > a_max:
            out.append(_cast(a_max, a.dtype))
        else:
            out.append(v)
    return ndarray(move(out), _copy_shape(a._shape), a.dtype)


def where(condition: Ref[ndarray], x: Ref[float | ndarray], y: Ref[float | ndarray]) -> ndarray:
    """numpy.where(cond, x, y) with array or scalar branches."""
    sh: list[int] = _copy_shape(condition._shape)
    dtx: str = "float64"
    dty: str = "float64"
    x_arr: bool = False
    y_arr: bool = False
    x_int: bool = False
    y_int: bool = False
    if isinstance(x, ndarray):
        sh = _broadcast_shape(sh, x._shape)
        dtx = x.dtype
        x_arr = True
    else:
        x_int = _is_integral(float(x))
        if x_int:
            dtx = "int64"
    if isinstance(y, ndarray):
        sh = _broadcast_shape(sh, y._shape)
        dty = y.dtype
        y_arr = True
    else:
        y_int = _is_integral(float(y))
        if y_int:
            dty = "int64"
    dt: str = _result_dtype(dtx, dty)
    if not x_arr and not y_arr:
        if not x_int or not y_int:
            dt = "float64"
    n: int = _size_of(sh)
    out: list[float] = []
    i: int = 0
    while i < n:
        c: float = condition._data[_src_index(condition._shape, sh, i)]
        v: float = 0.0
        if c != 0.0:
            if isinstance(x, ndarray):
                v = x._data[_src_index(x._shape, sh, i)]
            else:
                v = float(x)
        else:
            if isinstance(y, ndarray):
                v = y._data[_src_index(y._shape, sh, i)]
            else:
                v = float(y)
        out.append(_cast(v, dt))
        i = i + 1
    return ndarray(move(out), move(sh), dt)


def extract(condition: Ref[ndarray], a: Ref[ndarray]) -> ndarray:
    """numpy.extract: the elements of `a` where `condition` is true (a[mask])."""
    if len(condition._data) != len(a._data):
        raise ValueError("operands could not be broadcast together with shapes "
                         + _shape_compact(condition._shape) + " " + _shape_compact(a._shape))
    out: list[float] = []
    i: int = 0
    while i < len(a._data):
        if condition._data[i] != 0.0:
            out.append(a._data[i])
        i = i + 1
    n_out: int = len(out)
    return ndarray(move(out), [n_out], a.dtype)


def compress(condition: Ref[ndarray], a: Ref[ndarray]) -> ndarray:
    """numpy.compress over the flattened array."""
    return extract(condition, a)


def take(a: Ref[ndarray], indices: Ref[list[int]]) -> ndarray:
    """numpy.take over the flattened array (a[indices])."""
    n: int = len(a._data)
    out: list[float] = []
    for i in indices:
        j: int = i
        if j < 0:
            j = j + n
        if j < 0 or j >= n:
            raise IndexError("index " + str(i) + " is out of bounds for axis 0 with size " + str(n))
        out.append(a._data[j])
    n_out: int = len(out)
    return ndarray(move(out), [n_out], a.dtype)


def row(a: Ref[ndarray], i: int) -> ndarray:
    """Row `i` of a 2-D array as a 1-D array (numpy `a[i]`)."""
    if len(a._shape) != 2:
        raise IndexError("row() needs a 2-D array")
    rows: int = a._shape[0]
    cols: int = a._shape[1]
    r: int = i
    if r < 0:
        r = r + rows
    if r < 0 or r >= rows:
        raise IndexError("index " + str(i) + " is out of bounds for axis 0 with size " + str(rows))
    out: list[float] = []
    c: int = 0
    while c < cols:
        out.append(a._data[r * cols + c])
        c = c + 1
    return ndarray(move(out), [cols], a.dtype)


def column(a: Ref[ndarray], j: int) -> ndarray:
    """Column `j` of a 2-D array as a 1-D array (numpy `a[:, j]`)."""
    if len(a._shape) != 2:
        raise IndexError("column() needs a 2-D array")
    rows: int = a._shape[0]
    cols: int = a._shape[1]
    c: int = j
    if c < 0:
        c = c + cols
    if c < 0 or c >= cols:
        raise IndexError("index " + str(j) + " is out of bounds for axis 1 with size " + str(cols))
    out: list[float] = []
    r: int = 0
    while r < rows:
        out.append(a._data[r * cols + c])
        r = r + 1
    return ndarray(move(out), [rows], a.dtype)


def slice_(a: Ref[ndarray], start: int, stop: int, step: int = 1) -> ndarray:
    """numpy `a[start:stop:step]` on a 1-D array (Python slice semantics)."""
    n: int = len(a._data)
    if step == 0:
        raise ValueError("slice step cannot be zero")
    lo: int = start
    hi: int = stop
    if lo < 0:
        lo = lo + n
    if hi < 0:
        hi = hi + n
    if lo < 0:
        lo = 0
    if hi > n:
        hi = n
    out: list[float] = []
    if step > 0:
        i: int = lo
        while i < hi and i < n:
            out.append(a._data[i])
            i = i + step
    else:
        if lo >= n:
            lo = n - 1
        k: int = lo
        while k > hi and k >= 0:
            out.append(a._data[k])
            k = k + step
    n_out: int = len(out)
    return ndarray(move(out), [n_out], a.dtype)


def repeat(a: Ref[ndarray], repeats: int) -> ndarray:
    """numpy.repeat over the flattened array."""
    out: list[float] = []
    for v in a._data:
        k: int = 0
        while k < repeats:
            out.append(v)
            k = k + 1
    n_out: int = len(out)
    return ndarray(move(out), [n_out], a.dtype)


def tile(a: Ref[ndarray], reps: int) -> ndarray:
    """numpy.tile of a 1-D array."""
    out: list[float] = []
    k: int = 0
    while k < reps:
        for v in a._data:
            out.append(v)
        k = k + 1
    n_out: int = len(out)
    return ndarray(move(out), [n_out], a.dtype)


def concatenate(a: Ref[ndarray], b: Ref[ndarray], axis: int = 0) -> ndarray:
    """numpy.concatenate((a, b), axis) for two arrays."""
    dt: str = _result_dtype(a.dtype, b.dtype)
    if len(a._shape) != len(b._shape):
        raise ValueError("all the input arrays must have same number of dimensions, but the array at index 0 has "
                         + str(len(a._shape)) + " dimension(s) and the array at index 1 has "
                         + str(len(b._shape)) + " dimension(s)")
    if len(a._shape) == 1:
        out: list[float] = [_cast(v, dt) for v in a._data]
        for v in b._data:
            out.append(_cast(v, dt))
        n_out: int = len(out)
        return ndarray(move(out), [n_out], dt)
    ax: int = axis
    if ax < 0:
        ax = ax + 2
    if ax == 0:
        if a._shape[1] != b._shape[1]:
            raise ValueError("all the input array dimensions except for the concatenation axis must match "
                             "exactly, but along dimension 1, the array at index 0 has size "
                             + str(a._shape[1]) + " and the array at index 1 has size " + str(b._shape[1]))
        out2: list[float] = [_cast(v, dt) for v in a._data]
        for v in b._data:
            out2.append(_cast(v, dt))
        return ndarray(move(out2), [a._shape[0] + b._shape[0], a._shape[1]], dt)
    if a._shape[0] != b._shape[0]:
        raise ValueError("all the input array dimensions except for the concatenation axis must match "
                         "exactly, but along dimension 0, the array at index 0 has size "
                         + str(a._shape[0]) + " and the array at index 1 has size " + str(b._shape[0]))
    out3: list[float] = []
    r: int = 0
    while r < a._shape[0]:
        c: int = 0
        while c < a._shape[1]:
            out3.append(_cast(a._data[r * a._shape[1] + c], dt))
            c = c + 1
        c = 0
        while c < b._shape[1]:
            out3.append(_cast(b._data[r * b._shape[1] + c], dt))
            c = c + 1
        r = r + 1
    return ndarray(move(out3), [a._shape[0], a._shape[1] + b._shape[1]], dt)


def vstack(a: Ref[ndarray], b: Ref[ndarray]) -> ndarray:
    """numpy.vstack((a, b)): 1-D inputs become rows."""
    ra: ndarray = a.reshape([1, len(a._data)]) if len(a._shape) == 1 else a.copy()
    rb: ndarray = b.reshape([1, len(b._data)]) if len(b._shape) == 1 else b.copy()
    return concatenate(ra, rb, 0)


def hstack(a: Ref[ndarray], b: Ref[ndarray]) -> ndarray:
    """numpy.hstack((a, b))."""
    if len(a._shape) == 1 and len(b._shape) == 1:
        return concatenate(a, b, 0)
    return concatenate(a, b, 1)


def append(a: Ref[ndarray], values: Ref[ndarray]) -> ndarray:
    """numpy.append (flattened)."""
    return concatenate(a.flatten(), values.flatten(), 0)


def diff(a: Ref[ndarray]) -> ndarray:
    """numpy.diff of a 1-D array."""
    out: list[float] = []
    i: int = 1
    while i < len(a._data):
        out.append(a._data[i] - a._data[i - 1])
        i = i + 1
    dt: str = a.dtype
    if dt == "bool":
        dt = "bool"
    n_out: int = len(out)
    return ndarray(move(out), [n_out], dt)


def _sort_values(xs: Ref[list[float]]) -> list[float]:
    """Ascending sort with nans last (numpy order)."""
    finite: list[float] = []
    nans: int = 0
    for v in xs:
        if _m_isnan(v):
            nans = nans + 1
        else:
            finite.append(v)
    out: list[float] = sorted(finite)
    k: int = 0
    while k < nans:
        out.append(nan)
        k = k + 1
    return out


def sort(a: Ref[ndarray]) -> ndarray:
    """numpy.sort along the last axis."""
    if len(a._shape) == 1:
        return ndarray(_sort_values(a._data), _copy_shape(a._shape), a.dtype)
    lanes: list[list[float]] = _lanes(a, 1)
    out: list[float] = []
    for lane in lanes:
        s: list[float] = _sort_values(lane)
        for v in s:
            out.append(v)
    return ndarray(move(out), _copy_shape(a._shape), a.dtype)


def _argsort_values(xs: Ref[list[float]]) -> list[float]:
    """Stable argsort with nans last."""
    pairs: list[tuple[float, int]] = []
    nan_idx: list[int] = []
    i: int = 0
    while i < len(xs):
        if _m_isnan(xs[i]):
            nan_idx.append(i)
        else:
            pairs.append((xs[i], i))
        i = i + 1
    ordered: list[tuple[float, int]] = sorted(pairs, key=lambda p: p[0])
    out: list[float] = [float(p[1]) for p in ordered]
    for j in nan_idx:
        out.append(float(j))
    return out


def argsort(a: Ref[ndarray]) -> ndarray:
    """numpy.argsort along the last axis (stable)."""
    if len(a._shape) == 1:
        return ndarray(_argsort_values(a._data), _copy_shape(a._shape), "int64")
    lanes: list[list[float]] = _lanes(a, 1)
    out: list[float] = []
    for lane in lanes:
        s: list[float] = _argsort_values(lane)
        for v in s:
            out.append(v)
    return ndarray(move(out), _copy_shape(a._shape), "int64")


def unique(a: Ref[ndarray]) -> ndarray:
    """numpy.unique: sorted distinct values (flattened)."""
    s: list[float] = _sort_values(a._data)
    out: list[float] = []
    for v in s:
        if len(out) == 0:
            out.append(v)
        elif _m_isnan(v):
            if not _m_isnan(out[len(out) - 1]):
                out.append(v)
        elif out[len(out) - 1] != v:
            out.append(v)
    n_out: int = len(out)
    return ndarray(move(out), [n_out], a.dtype)


def searchsorted(a: Ref[ndarray], v: float) -> int:
    """numpy.searchsorted (side='left') on a sorted 1-D array."""
    lo: int = 0
    hi: int = len(a._data)
    while lo < hi:
        mid: int = (lo + hi) // 2
        if a._data[mid] < v:
            lo = mid + 1
        else:
            hi = mid
    return lo


def array_equal(a: Ref[ndarray], b: Ref[ndarray]) -> bool:
    """numpy.array_equal."""
    if not _same_shape(a._shape, b._shape):
        return False
    i: int = 0
    while i < len(a._data):
        if a._data[i] != b._data[i]:
            return False
        i = i + 1
    return True


def isclose(a: Ref[ndarray], b: Ref[float | ndarray], rtol: float = 1e-05, atol: float = 1e-08) -> ndarray:
    """numpy.isclose: |a - b| <= atol + rtol * |b|."""
    diffs: ndarray = _binop(a, b, _SUB)
    scale: ndarray = abs(_binop_r(a, b, _ADD) - a) * rtol + atol
    out: list[float] = []
    i: int = 0
    while i < len(diffs._data):
        d: float = diffs._data[i]
        ok: bool = False
        if _m_isnan(d):
            ok = False
        elif _m_isinf(d):
            bv: float = _binop_r(a, b, _ADD)._data[i] - a._data[_src_index(a._shape, diffs._shape, i)]
            ok = a._data[_src_index(a._shape, diffs._shape, i)] == bv
        else:
            ok = _m_fabs(d) <= scale._data[i]
        out.append(_bool(ok))
        i = i + 1
    return ndarray(move(out), _copy_shape(diffs._shape), "bool")


def allclose(a: Ref[ndarray], b: Ref[float | ndarray], rtol: float = 1e-05, atol: float = 1e-08) -> bool:
    """numpy.allclose."""
    return isclose(a, b, rtol, atol).all()


def dot(a: Ref[ndarray], b: Ref[ndarray]) -> ndarray:
    """numpy.dot: vector·vector gives a 1-element array (use `.item()` or `vdot` for the scalar)."""
    return matmul(a, b)


def vdot(a: Ref[ndarray], b: Ref[ndarray]) -> float:
    """numpy.vdot: scalar dot product over the flattened arrays."""
    if len(a._data) != len(b._data):
        raise ValueError("shapes " + _shape_compact(a._shape) + " and " + _shape_compact(b._shape)
                         + " not aligned: " + str(len(a._data)) + " (dim 0) != " + str(len(b._data)) + " (dim 0)")
    t: float = 0.0
    i: int = 0
    while i < len(a._data):
        t = t + a._data[i] * b._data[i]
        i = i + 1
    return t


def inner(a: Ref[ndarray], b: Ref[ndarray]) -> float:
    """numpy.inner for 1-D arrays."""
    return vdot(a, b)


def outer(a: Ref[ndarray], b: Ref[ndarray]) -> ndarray:
    """numpy.outer."""
    out: list[float] = []
    for x in a._data:
        for y in b._data:
            out.append(x * y)
    return ndarray(move(out), [len(a._data), len(b._data)], _result_dtype(a.dtype, b.dtype))


def matmul(a: Ref[ndarray], b: Ref[ndarray]) -> ndarray:
    """numpy.matmul / `@` for 1-D and 2-D operands (a 1-D·1-D product is a 1-element array)."""
    dt: str = _result_dtype(a.dtype, b.dtype)
    if dt == "bool":
        dt = "bool"
    ar: int = _rows(a)
    ac: int = _cols(a)
    br: int = _rows(b)
    bc: int = _cols(b)
    if len(b._shape) == 1:
        br = b._shape[0]
        bc = 1
    if ac != br:
        raise ValueError("matmul: Input operand 1 has a mismatch in its core dimension 0, with gufunc signature "
                         "(n?,k),(k,m?)->(n?,m?) (size " + str(br) + " is different from " + str(ac) + ")")
    out: list[float] = []
    i: int = 0
    while i < ar:
        j: int = 0
        while j < bc:
            t: float = 0.0
            k: int = 0
            while k < ac:
                t = t + a._data[i * ac + k] * b._data[k * bc + j]
                k = k + 1
            out.append(_cast(t, dt))
            j = j + 1
        i = i + 1
    if len(a._shape) == 1 and len(b._shape) == 1:
        return ndarray(move(out), [1], dt)
    if len(a._shape) == 1:
        return ndarray(move(out), [bc], dt)
    if len(b._shape) == 1:
        return ndarray(move(out), [ar], dt)
    return ndarray(move(out), [ar, bc], dt)


def trace(a: Ref[ndarray]) -> float:
    """numpy.trace of a 2-D array."""
    if len(a._shape) != 2:
        raise ValueError("diag requires an array of at least two dimensions")
    n: int = a._shape[0]
    if a._shape[1] < n:
        n = a._shape[1]
    t: float = 0.0
    i: int = 0
    while i < n:
        t = t + a._data[i * a._shape[1] + i]
        i = i + 1
    return t


def diag(a: Ref[ndarray]) -> ndarray:
    """numpy.diag: diagonal of a 2-D array, or a diagonal matrix from a 1-D array."""
    if len(a._shape) == 1:
        n: int = a._shape[0]
        m: ndarray = zeros([n, n], a.dtype)
        i: int = 0
        while i < n:
            m._data[i * n + i] = a._data[i]
            i = i + 1
        return m
    k: int = a._shape[0]
    if a._shape[1] < k:
        k = a._shape[1]
    out: list[float] = []
    j: int = 0
    while j < k:
        out.append(a._data[j * a._shape[1] + j])
        j = j + 1
    return ndarray(move(out), [k], a.dtype)


def norm(a: Ref[ndarray]) -> float:
    """numpy.linalg.norm (Frobenius / 2-norm)."""
    t: float = 0.0
    for v in a._data:
        t = t + v * v
    return _m_sqrt(t)


def _lu_decompose(a: Ref[ndarray]) -> tuple[list[float], int, bool]:
    """In-place LU with partial pivoting: returns (factors, sign of permutation, singular flag)."""
    n: int = a._shape[0]
    m: list[float] = [v for v in a._data]
    sign: int = 1
    singular: bool = False
    k: int = 0
    while k < n:
        p: int = k
        best: float = _m_fabs(m[k * n + k])
        i: int = k + 1
        while i < n:
            if _m_fabs(m[i * n + k]) > best:
                best = _m_fabs(m[i * n + k])
                p = i
            i = i + 1
        if best == 0.0:
            singular = True
            k = k + 1
            continue
        if p != k:
            sign = -sign
            c: int = 0
            while c < n:
                tmp: float = m[k * n + c]
                m[k * n + c] = m[p * n + c]
                m[p * n + c] = tmp
                c = c + 1
        r: int = k + 1
        while r < n:
            f: float = m[r * n + k] / m[k * n + k]
            m[r * n + k] = f
            c2: int = k + 1
            while c2 < n:
                m[r * n + c2] = m[r * n + c2] - f * m[k * n + c2]
                c2 = c2 + 1
            r = r + 1
        k = k + 1
    return (m, sign, singular)


def det(a: Ref[ndarray]) -> float:
    """numpy.linalg.det via LU with partial pivoting."""
    if len(a._shape) != 2 or a._shape[0] != a._shape[1]:
        raise ValueError("Last 2 dimensions of the array must be square")
    n: int = a._shape[0]
    lu: tuple[list[float], int, bool] = _lu_decompose(a)
    if lu[2]:
        return 0.0
    d: float = float(lu[1])
    i: int = 0
    while i < n:
        d = d * lu[0][i * n + i]
        i = i + 1
    return d


def solve(a: Ref[ndarray], b: Ref[ndarray]) -> ndarray:
    """numpy.linalg.solve for a square system and a 1-D right-hand side (Gaussian elimination)."""
    if len(a._shape) != 2 or a._shape[0] != a._shape[1]:
        raise ValueError("Last 2 dimensions of the array must be square")
    n: int = a._shape[0]
    if len(b._data) != n:
        raise ValueError("solve: Input operand 1 has a mismatch in its core dimension 0")
    m: list[float] = [v for v in a._data]
    x: list[float] = [v for v in b._data]
    k: int = 0
    while k < n:
        p: int = k
        best: float = _m_fabs(m[k * n + k])
        i: int = k + 1
        while i < n:
            if _m_fabs(m[i * n + k]) > best:
                best = _m_fabs(m[i * n + k])
                p = i
            i = i + 1
        if best == 0.0:
            raise ValueError("Singular matrix")
        if p != k:
            c: int = 0
            while c < n:
                tmp: float = m[k * n + c]
                m[k * n + c] = m[p * n + c]
                m[p * n + c] = tmp
                c = c + 1
            tb: float = x[k]
            x[k] = x[p]
            x[p] = tb
        r: int = k + 1
        while r < n:
            f: float = m[r * n + k] / m[k * n + k]
            c2: int = k
            while c2 < n:
                m[r * n + c2] = m[r * n + c2] - f * m[k * n + c2]
                c2 = c2 + 1
            x[r] = x[r] - f * x[k]
            r = r + 1
        k = k + 1
    i2: int = n - 1
    while i2 >= 0:
        s: float = x[i2]
        j: int = i2 + 1
        while j < n:
            s = s - m[i2 * n + j] * x[j]
            j = j + 1
        x[i2] = s / m[i2 * n + i2]
        i2 = i2 - 1
    return ndarray(move(x), [n], "float64")


def inv(a: Ref[ndarray]) -> ndarray:
    """numpy.linalg.inv via Gauss-Jordan elimination with partial pivoting."""
    if len(a._shape) != 2 or a._shape[0] != a._shape[1]:
        raise ValueError("Last 2 dimensions of the array must be square")
    n: int = a._shape[0]
    m: list[float] = [v for v in a._data]
    inv_: ndarray = eye(n)
    k: int = 0
    while k < n:
        p: int = k
        best: float = _m_fabs(m[k * n + k])
        i: int = k + 1
        while i < n:
            if _m_fabs(m[i * n + k]) > best:
                best = _m_fabs(m[i * n + k])
                p = i
            i = i + 1
        if best == 0.0:
            raise ValueError("Singular matrix")
        if p != k:
            c: int = 0
            while c < n:
                tmp: float = m[k * n + c]
                m[k * n + c] = m[p * n + c]
                m[p * n + c] = tmp
                tmp2: float = inv_._data[k * n + c]
                inv_._data[k * n + c] = inv_._data[p * n + c]
                inv_._data[p * n + c] = tmp2
                c = c + 1
        piv: float = m[k * n + k]
        c3: int = 0
        while c3 < n:
            m[k * n + c3] = m[k * n + c3] / piv
            inv_._data[k * n + c3] = inv_._data[k * n + c3] / piv
            c3 = c3 + 1
        r: int = 0
        while r < n:
            if r != k:
                f: float = m[r * n + k]
                if f != 0.0:
                    c4: int = 0
                    while c4 < n:
                        m[r * n + c4] = m[r * n + c4] - f * m[k * n + c4]
                        inv_._data[r * n + c4] = inv_._data[r * n + c4] - f * inv_._data[k * n + c4]
                        c4 = c4 + 1
            r = r + 1
        k = k + 1
    return inv_


def transpose(a: Ref[ndarray]) -> ndarray:
    """numpy.transpose."""
    return a.transpose()


def reshape(a: Ref[ndarray], shape: Ref[int | tuple[int, int] | list[int]]) -> ndarray:
    """numpy.reshape."""
    return a.reshape(shape)


def ravel(a: Ref[ndarray]) -> ndarray:
    """numpy.ravel."""
    return a.flatten()


def size(a: Ref[ndarray]) -> int:
    """numpy.size."""
    return len(a._data)


def ndim(a: Ref[ndarray]) -> int:
    """numpy.ndim."""
    return len(a._shape)


def shape(a: Ref[ndarray]) -> list[int]:
    """numpy.shape (a list here, not a tuple)."""
    return _copy_shape(a._shape)