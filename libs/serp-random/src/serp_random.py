"""serp-random — drop-in `random` facade over the MT19937 core (CPython parity).

Pure Serpentine ([P] over the serp_random_core rtlib module). Function names,
signatures, and seeded output are identical to CPython's `random` module for
the surface below (error messages pinned to CPython 3.11). Divergences:
getrandbits caps at 63 bits natively (int64), and randrange/randint widths
must fit in int64.
"""
from __future__ import annotations
from serpentine import Ref, Mut, TypeVar
from serp_random_core import mt_seed, mt_seed_sys, mt_random, mt_getrandbits, mt_randbelow

T = TypeVar("T")


def seed(a: int | None = None) -> None:
    if a is None:
        mt_seed_sys()
        return
    mt_seed(a)


def random() -> float:
    return mt_random()


def getrandbits(k: int) -> int:
    return mt_getrandbits(k)


def randrange(start: int, stop: int | None = None, step: int = 1) -> int:
    if stop is None:
        if step != 1:
            raise TypeError("Missing a non-None stop argument")
        if start > 0:
            return mt_randbelow(start)
        raise ValueError("empty range for randrange()")
    width: int = stop - start
    if step == 1:
        if width > 0:
            return start + mt_randbelow(width)
        raise ValueError(f"empty range for randrange() ({start}, {stop}, {width})")
    if step == 0:
        raise ValueError("zero step for randrange()")
    n: int = 0
    if step > 0:
        n = (width + step - 1) // step
    else:
        n = (width + step + 1) // step
    if n <= 0:
        raise ValueError("empty range for randrange()")
    return start + step * mt_randbelow(n)


def randint(a: int, b: int) -> int:
    return randrange(a, b + 1)


def uniform(a: float, b: float) -> float:
    return a + (b - a) * random()


def choice(seq: Ref[list[T]]) -> T:
    return seq[mt_randbelow(len(seq))]


def shuffle(x: Mut[list[T]]) -> None:
    i: int = len(x) - 1
    while i > 0:
        j: int = mt_randbelow(i + 1)
        tmp: T = x[i]
        x[i] = x[j]
        x[j] = tmp
        i -= 1
