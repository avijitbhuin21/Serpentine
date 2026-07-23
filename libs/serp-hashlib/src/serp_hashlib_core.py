"""serp-hashlib-core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_hashlib_core import ...` (rtlib.py); under
CPython these delegate to the stdlib hashlib one-shot digests.
"""

import hashlib as _hashlib

__all__ = ["h_sha256_hex", "h_sha1_hex", "h_md5_hex"]


def h_sha256_hex(b):
    """Lowercase hex SHA-256 of a bytes value."""
    return _hashlib.sha256(b).hexdigest()


def h_sha1_hex(b):
    """Lowercase hex SHA-1 of a bytes value."""
    return _hashlib.sha1(b).hexdigest()


def h_md5_hex(b):
    """Lowercase hex MD5 of a bytes value."""
    return _hashlib.md5(b).hexdigest()
