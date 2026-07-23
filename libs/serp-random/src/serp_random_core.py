"""serp-random-core CPython delegate: MT19937 primitives over the stdlib generator.

The Serpentine compiler intercepts `from serp_random_core import ...` (rtlib.py)
and maps these to bit-for-bit MT19937 runtime primitives; under CPython this
module drives the stdlib's global Mersenne Twister so both worlds produce
identical seeded sequences.
"""

import random as _random

__all__ = ["mt_seed", "mt_seed_sys", "mt_random", "mt_getrandbits", "mt_randbelow"]


def mt_seed(n):
    """Seed the global MT19937 state from an integer (CPython semantics)."""
    _random.seed(n)


def mt_seed_sys():
    """Seed the global MT19937 state from OS entropy."""
    _random.seed()


def mt_random():
    """Uniform float in [0.0, 1.0) (genrand_res53)."""
    return _random.random()


def mt_getrandbits(k):
    """Random int with k random bits; native builds cap k at 63."""
    if k <= 0:
        raise ValueError("number of bits must be greater than zero")
    if k > 63:
        raise OverflowError("getrandbits(k) with k > 63 exceeds the native int width")
    return _random.getrandbits(k)


def mt_randbelow(n):
    """Random int in [0, n) via CPython's _randbelow_with_getrandbits rejection loop."""
    if n <= 0:
        return 0
    k = n.bit_length()
    r = _random.getrandbits(k)
    while r >= n:
        r = _random.getrandbits(k)
    return r
