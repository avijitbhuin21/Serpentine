"""serp-hashlib-core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_hashlib_core import ...` (rtlib.py); under
CPython these delegate to the stdlib hashlib one-shot digests.
"""

import hashlib as _hashlib
import hmac as _hmac

__all__ = ["h_sha256_hex", "h_sha1_hex", "h_md5_hex", "h_hmac", "h_pbkdf2", "h_compare"]

_NAMES = ("sha256", "sha1", "md5")


def _check(name):
    """Normalize a digest name, raising the runtime's message for unsupported ones."""
    low = name.lower()
    if low not in _NAMES:
        raise ValueError(f"unsupported hash type {name}")
    return low


def h_hmac(name, key, msg):
    """HMAC digest of msg under key with the named hash (sha256/sha1/md5)."""
    return _hmac.new(key, msg, _check(name)).digest()


def h_pbkdf2(name, password, salt, iterations, dklen):
    """PBKDF2-HMAC derived key; dklen <= 0 means the digest size."""
    low = _check(name)
    if iterations < 1:
        raise ValueError("iteration value must be greater than 0.")
    return _hashlib.pbkdf2_hmac(low, password, salt, iterations, dklen if dklen > 0 else None)


def h_compare(a, b):
    """Constant-time equality of two byte strings."""
    return _hmac.compare_digest(a, b)


def h_sha256_hex(b):
    """Lowercase hex SHA-256 of a bytes value."""
    return _hashlib.sha256(b).hexdigest()


def h_sha1_hex(b):
    """Lowercase hex SHA-1 of a bytes value."""
    return _hashlib.sha1(b).hexdigest()


def h_md5_hex(b):
    """Lowercase hex MD5 of a bytes value."""
    return _hashlib.md5(b).hexdigest()
