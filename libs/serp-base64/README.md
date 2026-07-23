# serp-base64

Drop-in replacement for CPython's `base64` module: bytes-in / bytes-out,
written in the Serpentine subset.

## API

- `b64encode(s, altchars=None)` / `b64decode(s, altchars=None, validate=False)`
- `standard_b64encode/decode`, `urlsafe_b64encode/decode`
- `b32encode(s)` / `b32decode(s, casefold=False)` — RFC 4648.
- `b16encode(s)` / `b16decode(s, casefold=False)` — uppercase hex.
- `utf8_bytes(s) -> list[int]` / `utf8_text(list[int]) -> str` — Serpentine
  extras kept for other libraries.

Divergences: decode errors raise `ValueError` (CPython raises
`binascii.Error`, a ValueError subclass); inputs must be bytes (CPython also
accepts ASCII str); a85/b85/b32hex variants are not provided.

## Install

```
serp add serp-base64
pip install serp-base64
```
