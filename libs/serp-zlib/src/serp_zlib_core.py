"""serp-zlib-core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_zlib_core import ...` (rtlib.py); this file
delegates to the stdlib zlib/gzip for CPython runs. Compressed output is a
valid zlib/deflate/gzip stream in both worlds, but the exact compressed bytes
may differ between worlds — only roundtrips and checksums are world-identical.
Errors are normalized: bad levels raise ValueError("Bad compression level"),
corrupt streams raise ValueError("invalid compressed data").
"""

import gzip as _gzip
import zlib as _zlib

__all__ = ["z_crc32", "z_adler32", "z_compress", "z_decompress",
           "z_deflate", "z_inflate", "z_gzip_compress", "z_gzip_decompress"]

MAX_OUT = 256 << 20
_TOO_BIG = "decompressed data exceeds limit (256 MiB)"


def _bounded(wbits, data):
    """Decompress with a hard output cap, mirroring the native runtime's bomb guard."""
    do = _zlib.decompressobj(wbits)
    out = do.decompress(data, MAX_OUT + 1)
    if len(out) > MAX_OUT or do.unconsumed_tail:
        raise ValueError(_TOO_BIG)
    out += do.flush()
    if len(out) > MAX_OUT:
        raise ValueError(_TOO_BIG)
    if not do.eof:
        raise ValueError("invalid compressed data")
    return out


def _check_level(level):
    """Reject compression levels outside 0..9 (normalized error message)."""
    if level < 0 or level > 9:
        raise ValueError("Bad compression level")


def z_crc32(data, value):
    """CRC-32 of data continued from a running value."""
    return _zlib.crc32(data, value)


def z_adler32(data, value):
    """Adler-32 of data continued from a running value."""
    return _zlib.adler32(data, value)


def z_compress(data, level):
    """Compress data into a zlib-format stream at the given level (0..9)."""
    _check_level(level)
    return _zlib.compress(data, level)


def z_decompress(data):
    """Decompress a zlib-format stream; raises ValueError on corrupt input."""
    try:
        return _bounded(15, data)
    except _zlib.error:
        raise ValueError("invalid compressed data")


def z_deflate(data, level):
    """Compress data into a raw DEFLATE stream (no zlib header/trailer)."""
    _check_level(level)
    co = _zlib.compressobj(level, _zlib.DEFLATED, -15)
    return co.compress(data) + co.flush()


def z_inflate(data):
    """Decompress a raw DEFLATE stream; raises ValueError on corrupt input."""
    try:
        return _bounded(-15, data)
    except _zlib.error:
        raise ValueError("invalid compressed data")


def z_gzip_compress(data, level):
    """Compress data into a gzip stream at the given level (0..9)."""
    _check_level(level)
    return _gzip.compress(data, level, mtime=0)


def z_gzip_decompress(data):
    """Decompress a gzip stream (all members, NUL padding skipped); raises ValueError on corrupt input."""
    out = b""
    first = True
    while True:
        if not first:
            data = data.lstrip(b"\x00")
        if not data:
            return out
        first = False
        try:
            if len(data) < 10 or data[0:2] != b"\x1f\x8b" or data[2] != 8:
                raise ValueError("invalid compressed data")
            flg = data[3]
            i = 10
            if flg & 0x04:
                if i + 2 > len(data):
                    raise ValueError("invalid compressed data")
                i += 2 + int.from_bytes(data[i:i + 2], "little")
            for bit in (0x08, 0x10):
                if flg & bit:
                    while i < len(data) and data[i] != 0:
                        i += 1
                    i += 1
            if flg & 0x02:
                i += 2
            do = _zlib.decompressobj(-15)
            body = do.decompress(data[i:], MAX_OUT + 1 - len(out))
            if len(out) + len(body) > MAX_OUT or do.unconsumed_tail:
                raise ValueError(_TOO_BIG)
            if not do.eof or len(do.unused_data) < 8:
                raise ValueError("invalid compressed data")
            tail = do.unused_data
            if _zlib.crc32(body) != int.from_bytes(tail[0:4], "little") \
                    or len(body) & 0xFFFFFFFF != int.from_bytes(tail[4:8], "little"):
                raise ValueError("invalid compressed data")
        except _zlib.error:
            raise ValueError("invalid compressed data")
        out += body
        data = tail[8:]
