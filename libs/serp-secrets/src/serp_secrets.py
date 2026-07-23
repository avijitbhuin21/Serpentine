"""serp-secrets — drop-in `secrets` facade over the OS CSPRNG core.

Pure Serpentine ([P] over the serp_secrets_core rtlib module). Names and
signatures match CPython's `secrets` module. Divergences: randbits caps at
63 bits natively (int64); compare_digest is a plain equality check (no
constant-time guarantee); SystemRandom is not provided.
"""
from __future__ import annotations
from serpentine import Ref, TypeVar
from serp_secrets_core import s_token_hex, s_token_urlsafe, s_randbelow, s_randbits, s_token_bytes

T = TypeVar("T")

DEFAULT_ENTROPY: int = 32


def token_bytes(nbytes: int | None = None) -> bytes:
    if nbytes is None:
        return s_token_bytes(32)
    return s_token_bytes(nbytes)


def token_hex(nbytes: int | None = None) -> str:
    if nbytes is None:
        return s_token_hex(32)
    return s_token_hex(nbytes)


def token_urlsafe(nbytes: int | None = None) -> str:
    if nbytes is None:
        return s_token_urlsafe(32)
    return s_token_urlsafe(nbytes)


def randbelow(exclusive_upper_bound: int) -> int:
    return s_randbelow(exclusive_upper_bound)


def randbits(k: int) -> int:
    return s_randbits(k)


def choice(seq: Ref[list[T]]) -> T:
    if len(seq) == 0:
        raise IndexError("Cannot choose from an empty sequence")
    return seq[s_randbelow(len(seq))]


def compare_digest(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff: int = 0
    for i in range(len(a)):
        if a[i] != b[i]:
            diff += 1
    return diff == 0
