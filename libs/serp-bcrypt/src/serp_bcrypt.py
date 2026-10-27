"""serp-bcrypt — drop-in for the `bcrypt` package (pyca/bcrypt) API.

`gensalt(rounds=12, prefix=b"2b")`, `hashpw(password, salt)`, `checkpw(password,
hashed_password)` and `kdf`-free usage match pyca/bcrypt 4.x byte-for-byte: hashes
are `$2b$NN$<22-char salt><31-char hash>`, passwords are NUL-terminated and
truncated at 72 bytes, `$2a$`/`$2y$` settings are accepted, and checkpw
compares in constant time. Native builds run EksBlowfish in the Serpentine
runtime; CPython runs use a pure-Python delegate (no third-party packages).

Caps: no `kdf()` (bcrypt_pbkdf); errors are ValueError("Invalid salt") for any
malformed salt or hash.
"""
from __future__ import annotations
from serp_bcrypt_core import b_hash, b_gensalt
from serp_hashlib_core import h_compare


def gensalt(rounds: int = 12, prefix: bytes = b"2b") -> bytes:
    """A new random salt/setting string for hashpw."""
    return b_gensalt(rounds, prefix.decode("utf-8")).encode("utf-8")


def hashpw(password: bytes, salt: bytes) -> bytes:
    """Hash a password with a salt from gensalt() (or an existing hash, to re-derive it)."""
    return b_hash(password, salt.decode("utf-8")).encode("utf-8")


def checkpw(password: bytes, hashed_password: bytes) -> bool:
    """True when password matches hashed_password (constant-time comparison)."""
    return h_compare(hashpw(password, hashed_password), hashed_password)
