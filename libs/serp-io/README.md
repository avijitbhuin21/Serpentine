# serp-io

File helpers for Serpentine, on top of the language's built-in text/binary
file IO. Pure Serpentine ([P]) — the same source dual-runs under CPython.

Published on PyPI as **`serpentine-io`** (the `serp-io` name is rejected by PyPI as too
similar to an existing project); the import name is still `serp_io`:

```
serp add serpentine-io
pip install serpentine-io
```

```python
from serp_io import read_bytes, write_bytes, read_lines, reader

write_bytes("blob.bin", b"\x00\x01\x02")
print(read_bytes("blob.bin"))

r = reader(b"hello world")
print(r.read(5))       # b'hello'
print(r.remaining())   # 6
```

## API

- `read_bytes(path) -> bytes` / `write_bytes(path, data) -> int` / `append_bytes(path, data) -> int`
- `read_text(path) -> str` / `write_text(path, text) -> int` / `append_text(path, text) -> int`
- `read_lines(path) -> list[str]` — splits on `\n`, strips trailing `\r`, drops the final empty line
- `file_size(path) -> int` — byte length
- `copy_file(src, dst) -> int` — byte-exact copy
- `ByteReader` — position-tracked reads over bytes: `read(n)`, `read_all()`, `peek(n)`, `seek(pos)`, `skip(n)`, `tell()`, `remaining()`, `at_eof()`
- `reader(data: bytes) -> ByteReader` / `file_reader(path) -> ByteReader`

## Divergence

Native text-mode IO reads and writes raw bytes (no `\r\n` translation),
while CPython's text mode performs universal-newline translation on
Windows. Text written and read back in the same world is identical; use
the binary helpers when exact on-disk bytes matter.
