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
        return _zlib.decompress(data)
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
        do = _zlib.decompressobj(-15)
        out = do.decompress(data) + do.flush()
        if not do.eof:
            raise ValueError("invalid compressed data")
        return out
    except _zlib.error:
        raise ValueError("invalid compressed data")


def z_gzip_compress(data, level):
    """Compress data into a gzip stream at the given level (0..9)."""
    _check_level(level)
    return _gzip.compress(data, level, mtime=0)


def z_gzip_decompress(data):
    """Decompress a gzip stream; raises ValueError on corrupt input."""
    try:
        return _gzip.decompress(data)
    except (OSError, EOFError, _zlib.error):
        raise ValueError("invalid compressed data")
