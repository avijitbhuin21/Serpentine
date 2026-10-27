"""serp-hmac — drop-in `hmac` replacement (keyed hashing, RFC 2104).

Pure Serpentine over the serp_hashlib_core runtime primitives: native builds
compute HMAC and constant-time comparison in the runtime; CPython runs
delegate to the stdlib. `new(key, msg, digestmod)`, `HMAC.update/digest/
hexdigest/copy`, `name`/`digest_size`/`block_size`, `digest()` and
`compare_digest()` match the stdlib.

Caps: `digestmod` must be a name string ('sha256', 'sha1', 'md5'), not a
hashlib constructor or module; `compare_digest` takes bytes only; update()
re-hashes the accumulated message (O(n) memory).
"""
from __future__ import annotations
from serpentine import Mut, Ref, dataclass
from serp_hashlib_core import h_hmac, h_compare

def _size_of(alg: str) -> int:
    """Digest size in bytes of a supported hash name (0 when unsupported)."""
    if alg == "sha256":
        return 32
    if alg == "sha1":
        return 20
    if alg == "md5":
        return 16
    return 0


def _digest_name(digestmod: str) -> str:
    """Validate a digest name the way hmac.new does (missing → TypeError)."""
    if digestmod == "":
        raise TypeError("Missing required parameter 'digestmod'.")
    low: str = digestmod.lower()
    if _size_of(low) == 0:
        raise ValueError(f"unsupported hash type {digestmod}")
    return low


@dataclass
class HMAC:
    _key: bytes
    _msg: bytes
    _alg: str

    @property
    def name(self: Ref[HMAC]) -> str:
        return "hmac-" + self._alg

    @property
    def digest_size(self: Ref[HMAC]) -> int:
        return _size_of(self._alg)

    @property
    def block_size(self: Ref[HMAC]) -> int:
        return 64

    def update(self: Mut[HMAC], msg: bytes) -> None:
        self._msg = self._msg + msg

    def digest(self: Ref[HMAC]) -> bytes:
        return h_hmac(self._alg, self._key, self._msg)

    def hexdigest(self: Ref[HMAC]) -> str:
        return h_hmac(self._alg, self._key, self._msg).hex()

    def copy(self: Ref[HMAC]) -> HMAC:
        return HMAC(self._key, self._msg, self._alg)


def new(key: bytes, msg: bytes | None = None, digestmod: str = "") -> HMAC:
    """Create a keyed HMAC object (hmac.new)."""
    alg: str = _digest_name(digestmod)
    if msg is None:
        return HMAC(key, b"", alg)
    return HMAC(key, msg, alg)


def digest(key: bytes, msg: bytes, digest: str) -> bytes:
    """One-shot HMAC digest (hmac.digest)."""
    return h_hmac(_digest_name(digest), key, msg)


def compare_digest(a: bytes, b: bytes) -> bool:
    """Constant-time comparison that does not leak where the inputs differ."""
    return h_compare(a, b)
