"""serp-secrets-core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_secrets_core import ...` (rtlib.py); this file
delegates to the stdlib secrets module with the same error contracts as the
native runtime.
"""

import secrets as _secrets

__all__ = ["s_token_hex", "s_token_urlsafe", "s_randbelow", "s_randbits", "s_token_bytes"]


def s_token_hex(n):
    """n random bytes as lowercase hex (2n characters)."""
    if n < 0:
        raise ValueError("negative argument not allowed")
    return _secrets.token_hex(n)


def s_token_urlsafe(n):
    """n random bytes as unpadded URL-safe base64."""
    if n < 0:
        raise ValueError("negative argument not allowed")
    return _secrets.token_urlsafe(n)


def s_randbelow(n):
    """Uniform random int in [0, n); ValueError when n <= 0."""
    if n <= 0:
        raise ValueError("Upper bound must be positive.")
    return _secrets.randbelow(n)


def s_randbits(k):
    """k random bits from the OS CSPRNG; native builds cap k at 63."""
    if k <= 0:
        raise ValueError("number of bits must be greater than zero")
    if k > 63:
        raise OverflowError("randbits(k) with k > 63 exceeds the native int width")
    return _secrets.randbits(k)


def s_token_bytes(n):
    """n random bytes from the OS CSPRNG."""
    if n < 0:
        raise ValueError("negative argument not allowed")
    return _secrets.token_bytes(n)
