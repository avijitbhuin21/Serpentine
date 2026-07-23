"""serp-zlib — drop-in `zlib` facade over the runtime DEFLATE core.

Pure Serpentine ([P] over the serp_zlib_core rtlib module). Names and
signatures match CPython's zlib for crc32/adler32/compress/decompress
(decompress supports wbits 15 = zlib, -15 = raw DEFLATE, 31 = gzip).
deflate/inflate/gzip_compress/gzip_decompress are Serpentine extras.
Divergences: compressed bytes differ between worlds (different encoders,
fully interoperable); decode errors raise ValueError (CPython: zlib.error);
compressobj/decompressobj are not provided.
"""
from __future__ import annotations
from serp_zlib_core import (z_crc32, z_adler32, z_compress, z_decompress,
                            z_deflate, z_inflate, z_gzip_compress, z_gzip_decompress)

MAX_WBITS: int = 15
DEFLATED: int = 8
Z_DEFAULT_COMPRESSION: int = -1
Z_BEST_COMPRESSION: int = 9
Z_BEST_SPEED: int = 1
Z_NO_COMPRESSION: int = 0


def crc32(data: bytes, value: int = 0) -> int:
    return z_crc32(data, value)


def adler32(data: bytes, value: int = 1) -> int:
    return z_adler32(data, value)


def compress(data: bytes, level: int = -1) -> bytes:
    lv: int = level
    if lv == -1:
        lv = 6
    return z_compress(data, lv)


def decompress(data: bytes, wbits: int = 15) -> bytes:
    if wbits == 15:
        return z_decompress(data)
    if wbits == -15:
        return z_inflate(data)
    if wbits == 31:
        return z_gzip_decompress(data)
    raise ValueError(f"unsupported wbits value: {wbits}")


def deflate(data: bytes, level: int = -1) -> bytes:
    lv: int = level
    if lv == -1:
        lv = 6
    return z_deflate(data, lv)


def inflate(data: bytes) -> bytes:
    return z_inflate(data)


def gzip_compress(data: bytes, level: int = -1) -> bytes:
    lv: int = level
    if lv == -1:
        lv = 6
    return z_gzip_compress(data, lv)


def gzip_decompress(data: bytes) -> bytes:
    return z_gzip_decompress(data)
