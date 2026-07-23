# serp-secrets

Drop-in replacement for CPython's `secrets` module: native builds draw from
the OS CSPRNG (BCryptGenRandom on Windows, /dev/urandom elsewhere) with
rejection sampling; under CPython the `serp_secrets_core` delegate uses
stdlib `secrets`.

## API

- `token_bytes(nbytes=None)` / `token_hex(nbytes=None)` / `token_urlsafe(nbytes=None)`
  — default entropy is 32 bytes, like CPython.
- `randbelow(n)` — uniform in `[0, n)`; `ValueError` if `n <= 0`.
- `randbits(k)` — k ≤ 63 (native int64 cap).
- `choice(seq)` — over lists of Copy elements.
- `compare_digest(a, b)` — plain equality (no constant-time guarantee).
- `DEFAULT_ENTROPY`

`SystemRandom` is not provided.

## Install

```
serp add serp-secrets
pip install serp-secrets
```
