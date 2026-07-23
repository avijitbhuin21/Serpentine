"""serp-base64 — drop-in `base64` facade (bytes-first) in the Serpentine subset.

Pure Serpentine ([P]). b64/b32/b16 encode and decode operate on bytes like
CPython's base64 module. Divergences: decode errors raise ValueError (CPython
raises binascii.Error, a ValueError subclass), inputs must be bytes (CPython
also accepts ASCII str), and a85/b85/b32hex variants are not provided.
utf8_bytes/utf8_text are Serpentine-specific extras kept for other libraries.
No bitwise operators exist in the subset, so bit packing uses arithmetic.
"""
from __future__ import annotations
from serpentine import Ref

B64_ALPHABET: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
B64_URLSAFE: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
B32_ALPHABET: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
HEX_ALPHABET: str = "0123456789ABCDEF"


def _pow2(n: int) -> int:
    out: int = 1
    i: int = 0
    while i < n:
        out *= 2
        i += 1
    return out


def _encode64(data: bytes, alphabet: str) -> bytes:
    out: list[int] = []
    i: int = 0
    n: int = len(data)
    while i + 2 < n:
        v: int = data[i] * 65536 + data[i + 1] * 256 + data[i + 2]
        out.append(ord(alphabet[v // 262144]))
        out.append(ord(alphabet[(v // 4096) % 64]))
        out.append(ord(alphabet[(v // 64) % 64]))
        out.append(ord(alphabet[v % 64]))
        i += 3
    rem: int = n - i
    if rem == 1:
        v1: int = data[i] * 65536
        out.append(ord(alphabet[v1 // 262144]))
        out.append(ord(alphabet[(v1 // 4096) % 64]))
        out.append(61)
        out.append(61)
    elif rem == 2:
        v2: int = data[i] * 65536 + data[i + 1] * 256
        out.append(ord(alphabet[v2 // 262144]))
        out.append(ord(alphabet[(v2 // 4096) % 64]))
        out.append(ord(alphabet[(v2 // 64) % 64]))
        out.append(61)
    return bytes(out)


def _decode64(s: bytes, alphabet: str, validate: bool) -> bytes:
    filtered: list[int] = []
    for i in range(len(s)):
        b: int = s[i]
        c: str = chr(b)
        if alphabet.find(c) >= 0 or b == 61:
            filtered.append(b)
        elif validate:
            raise ValueError("Only base64 data is allowed")
    if len(filtered) % 4 != 0:
        raise ValueError("Invalid base64-encoded string")
    out: list[int] = []
    j: int = 0
    n: int = len(filtered)
    while j < n:
        b2: int = filtered[j + 2]
        b3: int = filtered[j + 3]
        pad: int = 0
        if b3 == 61:
            pad = 1
            if b2 == 61:
                pad = 2
        if pad > 0 and j + 4 != n:
            raise ValueError("Invalid base64-encoded string")
        k0: int = alphabet.find(chr(filtered[j]))
        k1: int = alphabet.find(chr(filtered[j + 1]))
        k2: int = 0
        k3: int = 0
        if pad < 2:
            k2 = alphabet.find(chr(b2))
        if pad < 1:
            k3 = alphabet.find(chr(b3))
        if k0 < 0 or k1 < 0 or k2 < 0 or k3 < 0:
            raise ValueError("Invalid base64-encoded string")
        v: int = k0 * 262144 + k1 * 4096 + k2 * 64 + k3
        out.append(v // 65536)
        if pad < 2:
            out.append((v // 256) % 256)
        if pad < 1:
            out.append(v % 256)
        j += 4
    return bytes(out)


def _alphabet64(altchars: bytes | None) -> str:
    if altchars is None:
        return B64_ALPHABET
    if len(altchars) != 2:
        raise ValueError("altchars must be a 2-byte value")
    return B64_ALPHABET[0:62] + chr(altchars[0]) + chr(altchars[1])


def b64encode(s: bytes, altchars: bytes | None = None) -> bytes:
    return _encode64(s, _alphabet64(altchars))


def b64decode(s: bytes, altchars: bytes | None = None, validate: bool = False) -> bytes:
    return _decode64(s, _alphabet64(altchars), validate)


def standard_b64encode(s: bytes) -> bytes:
    return _encode64(s, B64_ALPHABET)


def standard_b64decode(s: bytes) -> bytes:
    return _decode64(s, B64_ALPHABET, False)


def urlsafe_b64encode(s: bytes) -> bytes:
    return _encode64(s, B64_URLSAFE)


def urlsafe_b64decode(s: bytes) -> bytes:
    return _decode64(s, B64_URLSAFE, False)


def b32encode(s: bytes) -> bytes:
    out: list[int] = []
    i: int = 0
    n: int = len(s)
    acc: int = 0
    bits: int = 0
    while i < n:
        acc = acc * 256 + s[i]
        bits += 8
        i += 1
        while bits >= 5:
            bits -= 5
            div: int = _pow2(bits)
            out.append(ord(B32_ALPHABET[acc // div]))
            acc = acc % div
    if bits > 0:
        out.append(ord(B32_ALPHABET[acc * _pow2(5 - bits)]))
    while len(out) % 8 != 0:
        out.append(61)
    return bytes(out)


def b32decode(s: bytes, casefold: bool = False) -> bytes:
    text: str = s.decode()
    if casefold:
        text = text.upper()
    if len(text) % 8 != 0:
        raise ValueError("Incorrect padding")
    body: str = text
    while body.endswith("="):
        body = body[:len(body) - 1]
    out: list[int] = []
    acc: int = 0
    bits: int = 0
    for c in body:
        idx: int = B32_ALPHABET.find(c)
        if idx < 0:
            raise ValueError("Non-base32 digit found")
        acc = acc * 32 + idx
        bits += 5
        if bits >= 8:
            bits -= 8
            div: int = _pow2(bits)
            out.append(acc // div)
            acc = acc % div
    if acc != 0:
        raise ValueError("Non-zero padding bits in base32 input")
    return bytes(out)


def b16encode(s: bytes) -> bytes:
    out: list[int] = []
    for i in range(len(s)):
        b: int = s[i]
        out.append(ord(HEX_ALPHABET[b // 16]))
        out.append(ord(HEX_ALPHABET[b % 16]))
    return bytes(out)


def b16decode(s: bytes, casefold: bool = False) -> bytes:
    text: str = s.decode()
    if casefold:
        text = text.upper()
    if len(text) % 2 != 0:
        raise ValueError("Odd-length string")
    out: list[int] = []
    i: int = 0
    while i < len(text):
        hi: int = HEX_ALPHABET.find(text[i])
        lo: int = HEX_ALPHABET.find(text[i + 1])
        if hi < 0 or lo < 0:
            raise ValueError("Non-base16 digit found")
        out.append(hi * 16 + lo)
        i += 2
    return bytes(out)


def utf8_bytes(s: str) -> list[int]:
    out: list[int] = []
    for ch in s:
        cp: int = ord(ch)
        if cp < 128:
            out.append(cp)
        elif cp < 2048:
            out.append(192 + cp // 64)
            out.append(128 + cp % 64)
        elif cp < 65536:
            out.append(224 + cp // 4096)
            out.append(128 + (cp // 64) % 64)
            out.append(128 + cp % 64)
        else:
            out.append(240 + cp // 262144)
            out.append(128 + (cp // 4096) % 64)
            out.append(128 + (cp // 64) % 64)
            out.append(128 + cp % 64)
    return out


def _cont(b: int) -> int:
    if b < 128 or b >= 192:
        raise ValueError("invalid UTF-8 continuation byte")
    return b - 128


def utf8_text(data: Ref[list[int]]) -> str:
    out: list[str] = []
    i: int = 0
    n: int = len(data)
    while i < n:
        b0: int = data[i]
        if b0 < 0 or b0 > 255:
            raise ValueError(f"byte out of range: {b0}")
        if b0 < 128:
            out.append(chr(b0))
            i += 1
        elif b0 >= 194 and b0 < 224:
            if i + 1 >= n:
                raise ValueError("truncated UTF-8 sequence")
            out.append(chr((b0 - 192) * 64 + _cont(data[i + 1])))
            i += 2
        elif b0 >= 224 and b0 < 240:
            if i + 2 >= n:
                raise ValueError("truncated UTF-8 sequence")
            cp: int = (b0 - 224) * 4096 + _cont(data[i + 1]) * 64 + _cont(data[i + 2])
            if cp < 2048:
                raise ValueError("overlong UTF-8 sequence")
            out.append(chr(cp))
            i += 3
        elif b0 >= 240 and b0 < 245:
            if i + 3 >= n:
                raise ValueError("truncated UTF-8 sequence")
            cp2: int = ((b0 - 240) * 262144 + _cont(data[i + 1]) * 4096
                        + _cont(data[i + 2]) * 64 + _cont(data[i + 3]))
            if cp2 < 65536 or cp2 > 1114111:
                raise ValueError("invalid UTF-8 code point")
            out.append(chr(cp2))
            i += 4
        else:
            raise ValueError(f"invalid UTF-8 lead byte: {b0}")
    return "".join(out)
