# serp-hashlib

Drop-in replacement for CPython's `hashlib` object API (sha256/sha1/md5).
Native builds use self-contained SHA-256 / SHA-1 / MD5 implementations in the
runtime (no crates); under CPython the `serp_hashlib_core` delegate uses stdlib
`hashlib`. Digests are bit-identical across both worlds.

## API

- `sha256(data=None)` / `sha1(data=None)` / `md5(data=None)` — take optional
  initial bytes, return a hash object.
- Hash objects support `.update(data)`, `.hexdigest()`, `.digest()`, `.copy()`.

Divergences: `update()` re-hashes the accumulated buffer (O(n) memory); no
`name`/`digest_size` attributes, no `new()`, sha512/blake2 deferred.

## Install

```
serp add serp-hashlib
pip install serp-hashlib
```
