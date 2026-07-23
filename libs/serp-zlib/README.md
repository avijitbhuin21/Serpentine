# serp-zlib

Compression for Serpentine: zlib-format, raw-DEFLATE and gzip streams, plus
crc32/adler32 checksums. Runtime-backed ([R]): native builds use a
self-contained DEFLATE implementation in the Serpentine runtime; under
CPython the same imports delegate to the stdlib `zlib`/`gzip` modules.

```python
from serp_zlib import compress, decompress, crc32

data: bytes = b"hello hello hello"
z: bytes = compress(data, 6)
print(decompress(z) == data)   # True
print(crc32(data))
```

## API

- `crc32(data, value=0)` / `adler32(data, value=1)` — running-checksum `value`
  like stdlib zlib.
- `compress(data, level=-1)` (zlib format; -1 = default level 6) /
  `decompress(data, wbits=15)` — wbits routes the container: `15` zlib,
  `-15` raw DEFLATE, `31` gzip.
- `deflate(data, level=-1)` / `inflate(data)` — raw DEFLATE extras (used by serp-zipfile).
- `gzip_compress(data, level=-1)` / `gzip_decompress(data)`.
- Constants: `MAX_WBITS`, `DEFLATED`, `Z_DEFAULT_COMPRESSION`,
  `Z_BEST_COMPRESSION`, `Z_BEST_SPEED`, `Z_NO_COMPRESSION`.

Levels are 0 (stored) through 9. Bad levels raise
`ValueError("Bad compression level")`; corrupt streams raise
`ValueError("invalid compressed data")` (CPython raises `zlib.error`).
`compressobj`/`decompressobj` are not provided.

## Divergence

Compressed output is a valid stream in both worlds and fully interoperable
(each world decompresses the other's output), but the exact compressed bytes
differ between CPython's zlib and the native runtime's encoder. Only
roundtrips, decompressed content and checksums are world-identical.
