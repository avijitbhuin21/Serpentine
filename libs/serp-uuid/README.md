# serp-uuid

`uuid4()` for Serpentine ([R] runtime-backed): native builds draw 16 bytes
from the OS CSPRNG (BCryptGenRandom on Windows, /dev/urandom elsewhere) and
format an RFC 4122 version-4 UUID; under CPython this package delegates to
stdlib `uuid`.

## API

- `uuid4() -> UUID` — a random version-4 UUID, e.g.
  `"f47ac10b-58cc-4372-a567-0e02b2c3d479"`.
- `UUID(text)` — parse and normalize. Dashed, bare 32-hex, brace-wrapped and
  `urn:uuid:`-prefixed spellings are all accepted (any case); anything else
  raises `ValueError("badly formed hexadecimal UUID string")`.
- `parse(text)` — an alias for `UUID(text)`.
- `str(u)` / `u.hex` / `u.urn` / `u.version` / `u.variant`.

Caps: only version-4 generation, and no `.int` / `.bytes` / `.fields`
(a 128-bit int does not fit `int64`). `UUID(bytes=...)` /
`UUID(fields=...)` keyword forms are absent.

## Install

```
serp add serp-uuid
pip install serp-uuid
```
