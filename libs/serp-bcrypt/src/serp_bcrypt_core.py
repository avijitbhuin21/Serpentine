"""serp-bcrypt core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_bcrypt_core import ...` (rtlib.py); natively
the runtime runs EksBlowfish in Rust. This file is a pure-Python bcrypt with
the same contract so the library dual-runs without third-party packages. The
Blowfish P-array and S-boxes are the hexadecimal digits of pi, computed once
at import (Machin's formula) instead of being transcribed.

b_hash(password, setting) -> '$2b$NN$<22 salt><31 hash>' for a setting string
'$2a$/$2b$/$2y$NN$<22 salt>' (anything after the salt is ignored);
b_gensalt(rounds, prefix) -> setting string with 16 random bytes of salt.
Errors raise ValueError with the messages the runtime uses.
"""

import os as _os

__all__ = ["b_hash", "b_gensalt"]

_ALPHA = "./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_IDX = {c: i for i, c in enumerate(_ALPHA)}
_MAGIC = b"OrpheanBeholderScryDoubt"


def _arctan_inv(x: int, one: int) -> int:
    """one * atan(1/x) in fixed point."""
    total = term = one // x
    x2 = x * x
    n = 1
    sign = -1
    while term:
        term //= x2
        total += sign * (term // (2 * n + 1))
        sign = -sign
        n += 1
    return total


def _pi_words(count: int) -> list[int]:
    """The first `count` 32-bit words of pi's fractional hex expansion."""
    bits = 32 * count + 64
    one = 1 << bits
    pi = 16 * _arctan_inv(5, one) - 4 * _arctan_inv(239, one)
    frac = pi - (3 << bits)
    frac >>= 64
    out = []
    for i in range(count):
        shift = 32 * (count - 1 - i)
        out.append((frac >> shift) & 0xFFFFFFFF)
    return out


_WORDS = _pi_words(18 + 4 * 256)
_P0 = _WORDS[:18]
_S0 = [_WORDS[18 + 256 * k: 18 + 256 * (k + 1)] for k in range(4)]


def _b64_encode(data: bytes) -> str:
    """bcrypt's base64 variant (./A-Za-z0-9, no padding)."""
    out = []
    i = 0
    n = len(data)
    while i < n:
        c1 = data[i]
        i += 1
        out.append(_ALPHA[c1 >> 2])
        c1 = (c1 & 0x03) << 4
        if i >= n:
            out.append(_ALPHA[c1])
            break
        c2 = data[i]
        i += 1
        c1 |= c2 >> 4
        out.append(_ALPHA[c1])
        c1 = (c2 & 0x0F) << 2
        if i >= n:
            out.append(_ALPHA[c1])
            break
        c2 = data[i]
        i += 1
        c1 |= c2 >> 6
        out.append(_ALPHA[c1])
        out.append(_ALPHA[c2 & 0x3F])
    return "".join(out)


def _b64_decode(text: str, nbytes: int) -> bytes:
    """Decode bcrypt base64 into exactly nbytes bytes."""
    vals = []
    for ch in text:
        if ch not in _IDX:
            raise ValueError("Invalid salt")
        vals.append(_IDX[ch])
    out = bytearray()
    i = 0
    while len(out) < nbytes and i + 1 < len(vals):
        out.append(((vals[i] << 2) | (vals[i + 1] >> 4)) & 0xFF)
        if len(out) >= nbytes or i + 2 >= len(vals):
            break
        out.append(((vals[i + 1] << 4) | (vals[i + 2] >> 2)) & 0xFF)
        if len(out) >= nbytes or i + 3 >= len(vals):
            break
        out.append(((vals[i + 2] << 6) | vals[i + 3]) & 0xFF)
        i += 4
    if len(out) != nbytes:
        raise ValueError("Invalid salt")
    return bytes(out)


class _Blowfish:
    """Mutable Blowfish state for the EksBlowfish key schedule."""

    def __init__(self) -> None:
        self.p = list(_P0)
        self.s = [list(b) for b in _S0]

    def _f(self, x: int) -> int:
        s = self.s
        h = (s[0][x >> 24] + s[1][(x >> 16) & 0xFF]) & 0xFFFFFFFF
        return ((h ^ s[2][(x >> 8) & 0xFF]) + s[3][x & 0xFF]) & 0xFFFFFFFF

    def encrypt(self, l: int, r: int) -> tuple[int, int]:
        p = self.p
        for i in range(16):
            l ^= p[i]
            r ^= self._f(l)
            l, r = r, l
        l, r = r, l
        r ^= p[16]
        l ^= p[17]
        return l, r

    def expand(self, data: bytes, key: bytes) -> None:
        kpos = 0
        for i in range(18):
            w = 0
            for _ in range(4):
                w = (w << 8) | key[kpos]
                kpos = (kpos + 1) % len(key)
            self.p[i] ^= w
        dpos = 0
        l = r = 0

        def word() -> int:
            nonlocal dpos
            w = 0
            for _ in range(4):
                w = (w << 8) | (data[dpos] if data else 0)
                dpos = (dpos + 1) % len(data) if data else 0
            return w

        for i in range(0, 18, 2):
            l ^= word()
            r ^= word()
            l, r = self.encrypt(l, r)
            self.p[i], self.p[i + 1] = l, r
        for box in self.s:
            for i in range(0, 256, 2):
                l ^= word()
                r ^= word()
                l, r = self.encrypt(l, r)
                box[i], box[i + 1] = l, r


def _parse_setting(setting: str) -> tuple[str, int, bytes, str]:
    """Split '$2b$NN$salt' into (variant, cost, salt bytes, salt text)."""
    if len(setting) < 29 or setting[0] != "$" or setting[1] != "2" or setting[3] != "$" \
            or setting[6] != "$" or setting[2] not in "aby":
        raise ValueError("Invalid salt")
    if not setting[4:6].isdigit():
        raise ValueError("Invalid salt")
    cost = int(setting[4:6])
    if cost < 4 or cost > 31:
        raise ValueError("Invalid salt")
    salt_text = setting[7:29]
    return setting[2], cost, _b64_decode(salt_text, 16), salt_text


def b_hash(password: bytes, setting: str) -> str:
    """bcrypt hash string of password under the salt/cost in setting."""
    variant, cost, salt, salt_text = _parse_setting(setting)
    key = (password + b"\x00")[:72]
    bf = _Blowfish()
    bf.expand(salt, key)
    for _ in range(1 << cost):
        bf.expand(b"", key)
        bf.expand(b"", salt)
    words = [int.from_bytes(_MAGIC[i:i + 4], "big") for i in range(0, 24, 4)]
    for _ in range(64):
        for j in range(0, 6, 2):
            words[j], words[j + 1] = bf.encrypt(words[j], words[j + 1])
    raw = b"".join(w.to_bytes(4, "big") for w in words)
    return f"$2{variant}${cost:02d}${salt_text}{_b64_encode(raw[:23])}"


def b_gensalt(rounds: int, prefix: str) -> str:
    """A fresh setting string with 16 random salt bytes."""
    if prefix not in ("2a", "2b"):
        raise ValueError("Supported prefixes are b'2a' or b'2b'")
    if rounds < 4 or rounds > 31:
        raise ValueError("Invalid rounds")
    return f"${prefix}${rounds:02d}${_b64_encode(_os.urandom(16))}"
