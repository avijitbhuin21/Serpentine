"""serp-bigint — arbitrary-precision integers for Serpentine (where `int` is int64).

`BigInt` holds a sign and base-10**9 limbs and supports `+ - * // % **`, unary `-`, `abs`,
comparisons and equality, `divmod`, `str()`/`repr()`, construction from an int (`big(n)`) or a
decimal string (`BigInt.parse("123...")`), and `to_int()` when the value fits in int64.
Division and modulo follow Python's floor semantics for negative operands, so results match
CPython's unbounded `int` exactly.

Use it where values can exceed int64 (factorials, crypto-sized numbers, exact money in minor
units over huge sums). Plain `int` stays int64 with an OverflowError trap.
"""
from __future__ import annotations
from serpentine import Mut, Owned, Ref, dataclass, move

BASE: int = 1000000000
_INT64_MAX: int = 9223372036854775807


def _trim(limbs: Mut[list[int]]) -> None:
    """Drop high zero limbs (keeping at least one)."""
    while len(limbs) > 1 and limbs[len(limbs) - 1] == 0:
        limbs.pop()


def _cmp_mag(a: Ref[list[int]], b: Ref[list[int]]) -> int:
    """Compare magnitudes: -1, 0 or 1."""
    if len(a) != len(b):
        return -1 if len(a) < len(b) else 1
    i: int = len(a) - 1
    while i >= 0:
        if a[i] != b[i]:
            return -1 if a[i] < b[i] else 1
        i -= 1
    return 0


def _add_mag(a: Ref[list[int]], b: Ref[list[int]]) -> list[int]:
    """Magnitude sum."""
    out: list[int] = []
    carry: int = 0
    i: int = 0
    n: int = max(len(a), len(b))
    while i < n:
        s: int = carry
        if i < len(a):
            s += a[i]
        if i < len(b):
            s += b[i]
        out.append(s % BASE)
        carry = s // BASE
        i += 1
    if carry > 0:
        out.append(carry)
    return out


def _sub_mag(a: Ref[list[int]], b: Ref[list[int]]) -> list[int]:
    """Magnitude difference a - b (requires |a| >= |b|)."""
    out: list[int] = []
    borrow: int = 0
    i: int = 0
    while i < len(a):
        d: int = a[i] - borrow
        if i < len(b):
            d -= b[i]
        if d < 0:
            d += BASE
            borrow = 1
        else:
            borrow = 0
        out.append(d)
        i += 1
    _trim(out)
    return out


def _mul_mag(a: Ref[list[int]], b: Ref[list[int]]) -> list[int]:
    """Schoolbook magnitude product (limb products stay below 2**63)."""
    out: list[int] = []
    for k in range(len(a) + len(b)):
        out.append(0)
    for i in range(len(a)):
        carry: int = 0
        ai: int = a[i]
        j: int = 0
        while j < len(b) or carry > 0:
            cur: int = out[i + j] + carry
            if j < len(b):
                cur += ai * b[j]
            out[i + j] = cur % BASE
            carry = cur // BASE
            j += 1
    _trim(out)
    return out


def _mul_small(a: Ref[list[int]], m: int) -> list[int]:
    """Magnitude times a limb-sized non-negative int."""
    out: list[int] = []
    carry: int = 0
    for x in a:
        cur: int = x * m + carry
        out.append(cur % BASE)
        carry = cur // BASE
    while carry > 0:
        out.append(carry % BASE)
        carry = carry // BASE
    _trim(out)
    return out


def _divmod_mag(a: Ref[list[int]], b: Ref[list[int]]) -> list[list[int]]:
    """[quotient, remainder] magnitudes by long division (binary search per limb)."""
    q: list[int] = []
    for k in range(len(a)):
        q.append(0)
    rem: list[int] = [0]
    i: int = len(a) - 1
    while i >= 0:
        shifted: list[int] = [a[i]]
        for x in rem:
            shifted.append(x)
        _trim(shifted)
        lo: int = 0
        hi: int = BASE - 1
        while lo < hi:
            mid: int = (lo + hi + 1) // 2
            prod: list[int] = _mul_small(b, mid)
            if _cmp_mag(prod, shifted) <= 0:
                lo = mid
            else:
                hi = mid - 1
        q[i] = lo
        prod2: list[int] = _mul_small(b, lo)
        rem = _sub_mag(shifted, prod2)
        i -= 1
    _trim(q)
    out: list[list[int]] = []
    out.append(move(q))
    out.append(move(rem))
    return out


def _is_zero(limbs: Ref[list[int]]) -> bool:
    return len(limbs) == 1 and limbs[0] == 0


@dataclass
class BigInt:
    sign: int
    limbs: list[int]

    @staticmethod
    def parse(text: str) -> BigInt:
        """A BigInt from a decimal string (optional sign, underscores allowed like int())."""
        s: str = text.strip().replace("_", "")
        neg: bool = False
        if s.startswith("-") or s.startswith("+"):
            neg = s.startswith("-")
            s = s[1:len(s)]
        if s == "":
            raise ValueError(f"invalid literal for BigInt(): {text!r}")
        for ch in s:
            if ch < "0" or ch > "9":
                raise ValueError(f"invalid literal for BigInt(): {text!r}")
        limbs: list[int] = []
        end: int = len(s)
        while end > 0:
            start: int = end - 9 if end > 9 else 0
            limbs.append(int(s[start:end]))
            end = start
        _trim(limbs)
        sign: int = -1 if neg and not _is_zero(limbs) else 1
        return BigInt(sign, move(limbs))

    def __str__(self: Ref[BigInt]) -> str:
        top: int = len(self.limbs) - 1
        out: str = str(self.limbs[top])
        i: int = top - 1
        while i >= 0:
            chunk: str = str(self.limbs[i])
            while len(chunk) < 9:
                chunk = "0" + chunk
            out = out + chunk
            i -= 1
        return "-" + out if self.sign < 0 else out

    def __repr__(self: Ref[BigInt]) -> str:
        return "BigInt(" + self.__str__() + ")"

    def is_zero(self: Ref[BigInt]) -> bool:
        return _is_zero(self.limbs)

    def __neg__(self: Ref[BigInt]) -> BigInt:
        if _is_zero(self.limbs):
            return BigInt(1, [0])
        return BigInt(-self.sign, [x for x in self.limbs])

    def __abs__(self: Ref[BigInt]) -> BigInt:
        return BigInt(1, [x for x in self.limbs])

    def __add__(self: Ref[BigInt], other: Ref[BigInt]) -> BigInt:
        if self.sign == other.sign:
            return BigInt(self.sign, _add_mag(self.limbs, other.limbs))
        c: int = _cmp_mag(self.limbs, other.limbs)
        if c == 0:
            return BigInt(1, [0])
        if c > 0:
            return BigInt(self.sign, _sub_mag(self.limbs, other.limbs))
        return BigInt(other.sign, _sub_mag(other.limbs, self.limbs))

    def __sub__(self: Ref[BigInt], other: Ref[BigInt]) -> BigInt:
        neg: BigInt = -other
        return self + neg

    def __mul__(self: Ref[BigInt], other: Ref[BigInt]) -> BigInt:
        mag: list[int] = _mul_mag(self.limbs, other.limbs)
        if _is_zero(mag):
            return BigInt(1, move(mag))
        return BigInt(self.sign * other.sign, move(mag))

    def _floor_divmod(self: Ref[BigInt], other: Ref[BigInt]) -> list[BigInt]:
        if _is_zero(other.limbs):
            raise ZeroDivisionError("integer division or modulo by zero")
        parts: list[list[int]] = _divmod_mag(self.limbs, other.limbs)
        r: list[int] = parts.pop()
        q: list[int] = parts.pop()
        qs: int = self.sign * other.sign
        quo: BigInt = BigInt(1 if _is_zero(q) else qs, move(q))
        rem: BigInt = BigInt(1 if _is_zero(r) else self.sign, move(r))
        if not rem.is_zero() and qs < 0:
            one: BigInt = BigInt(1, [1])
            quo = quo - one
            rem = rem + other
        out: list[BigInt] = []
        out.append(move(quo))
        out.append(move(rem))
        return out

    def __floordiv__(self: Ref[BigInt], other: Ref[BigInt]) -> BigInt:
        res: list[BigInt] = self._floor_divmod(other)
        r: BigInt = res.pop()
        return res.pop()

    def __mod__(self: Ref[BigInt], other: Ref[BigInt]) -> BigInt:
        res: list[BigInt] = self._floor_divmod(other)
        return res.pop()

    def __pow__(self: Ref[BigInt], exponent: int) -> BigInt:
        if exponent < 0:
            raise ValueError("BigInt only supports non-negative exponents")
        result: BigInt = BigInt(1, [1])
        base: BigInt = BigInt(self.sign, [x for x in self.limbs])
        e: int = exponent
        while e > 0:
            if e % 2 == 1:
                result = result * base
            e = e // 2
            if e > 0:
                base = base * base
        return result

    def _cmp(self: Ref[BigInt], other: Ref[BigInt]) -> int:
        if self.sign != other.sign:
            return -1 if self.sign < other.sign else 1
        c: int = _cmp_mag(self.limbs, other.limbs)
        return c if self.sign > 0 else -c

    def __eq__(self: Ref[BigInt], other: Ref[BigInt]) -> bool:
        return self._cmp(other) == 0

    def __lt__(self: Ref[BigInt], other: Ref[BigInt]) -> bool:
        return self._cmp(other) < 0

    def __le__(self: Ref[BigInt], other: Ref[BigInt]) -> bool:
        return self._cmp(other) <= 0

    def __gt__(self: Ref[BigInt], other: Ref[BigInt]) -> bool:
        return self._cmp(other) > 0

    def __ge__(self: Ref[BigInt], other: Ref[BigInt]) -> bool:
        return self._cmp(other) >= 0

    def fits_int(self: Ref[BigInt]) -> bool:
        """True when the value is within int64."""
        lim: BigInt = BigInt.parse("9223372036854775807")
        low: BigInt = BigInt.parse("-9223372036854775808")
        return self._cmp(lim) <= 0 and self._cmp(low) >= 0

    def to_int(self: Ref[BigInt]) -> int:
        """The value as int (OverflowError outside int64)."""
        if not self.fits_int():
            raise OverflowError("BigInt too large to convert to int")
        if self.sign < 0 and self.__str__() == "-9223372036854775808":
            return -_INT64_MAX - 1
        v: int = 0
        i: int = len(self.limbs) - 1
        while i >= 0:
            v = v * BASE + self.limbs[i]
            i -= 1
        return v * self.sign


def big(n: int) -> BigInt:
    """A BigInt from an int."""
    return BigInt.parse(str(n))


def bigdivmod(a: Ref[BigInt], b: Ref[BigInt]) -> list[BigInt]:
    """[a // b, a % b] with Python floor semantics."""
    return a._floor_divmod(b)
