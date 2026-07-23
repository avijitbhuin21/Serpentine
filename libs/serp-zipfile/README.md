# serp-zipfile

ZIP archives for Serpentine: read and write archives with stored (method 0)
and DEFLATE (method 8) entries, UTF-8 names and CRC-verified extraction.
Pure Serpentine ([P]) over serp-zlib — the same source dual-runs under
CPython.

```python
from serp_zipfile import ZipEntry, zip_write, zip_read, zip_extract, zip_names
from serpentine import move

entries: list[ZipEntry] = []
e: ZipEntry = ZipEntry("hello.txt", b"hello zip")
entries.append(move(e))
zip_write("out.zip", entries, True)

back: list[ZipEntry] = zip_read("out.zip")
print(zip_names(back))
print(zip_extract(back, "hello.txt"))
```

## API

- `ZipEntry(name: str, data: bytes)` — one archive member
- `zip_bytes(entries, compress) -> bytes` / `zip_parse(data) -> list[ZipEntry]` — in-memory
- `zip_write(path, entries, compress)` / `zip_read(path) -> list[ZipEntry]` — on disk
- `zip_names(entries) -> list[str]`, `zip_has(entries, name) -> bool`, `zip_extract(entries, name) -> bytes`

With `compress=True` each entry is deflated and kept only if smaller than
the raw data (CPython zipfile behaves the same way). Written archives use a
fixed DOS timestamp (1980-01-01) so output is deterministic.

## Limits

No zip64 (4 GiB / 65535-entry caps), no encryption, no multi-disk archives,
no on-the-fly streaming. Archives produced here open fine in CPython's
`zipfile` and vice versa; exact archive bytes differ between worlds because
the DEFLATE encoders differ.
