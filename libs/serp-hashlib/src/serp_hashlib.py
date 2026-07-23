"""serp-hashlib — drop-in `hashlib` facade (object API over runtime digests).

Pure Serpentine ([P] over the serp_hashlib_core rtlib module). Usage matches
CPython: sha256(b"data").hexdigest(), incremental update(), digest(), copy().
Divergences: only sha256/sha1/md5 are provided; update() re-hashes the
accumulated buffer (O(n) memory); no name/digest_size attributes or new().
"""
from __future__ import annotations
from serpentine import Ref, Mut, dataclass
from serp_hashlib_core import h_sha256_hex, h_sha1_hex, h_md5_hex


@dataclass
class Sha256:
    buf: bytes

    def update(self: Mut[Sha256], data: bytes) -> None:
        self.buf = self.buf + data

    def hexdigest(self: Ref[Sha256]) -> str:
        return h_sha256_hex(self.buf)

    def digest(self: Ref[Sha256]) -> bytes:
        return bytes.fromhex(h_sha256_hex(self.buf))

    def copy(self: Ref[Sha256]) -> Sha256:
        return Sha256(self.buf)


@dataclass
class Sha1:
    buf: bytes

    def update(self: Mut[Sha1], data: bytes) -> None:
        self.buf = self.buf + data

    def hexdigest(self: Ref[Sha1]) -> str:
        return h_sha1_hex(self.buf)

    def digest(self: Ref[Sha1]) -> bytes:
        return bytes.fromhex(h_sha1_hex(self.buf))

    def copy(self: Ref[Sha1]) -> Sha1:
        return Sha1(self.buf)


@dataclass
class Md5:
    buf: bytes

    def update(self: Mut[Md5], data: bytes) -> None:
        self.buf = self.buf + data

    def hexdigest(self: Ref[Md5]) -> str:
        return h_md5_hex(self.buf)

    def digest(self: Ref[Md5]) -> bytes:
        return bytes.fromhex(h_md5_hex(self.buf))

    def copy(self: Ref[Md5]) -> Md5:
        return Md5(self.buf)


def sha256(data: bytes | None = None) -> Sha256:
    if data is None:
        return Sha256(b"")
    return Sha256(data)


def sha1(data: bytes | None = None) -> Sha1:
    if data is None:
        return Sha1(b"")
    return Sha1(data)


def md5(data: bytes | None = None) -> Md5:
    if data is None:
        return Md5(b"")
    return Md5(data)
