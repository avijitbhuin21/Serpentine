"""Accept helper module: a bin-1 Serpentine module imported by main.py (SPEC section 9)."""

from serpentine import Ref


def mean(xs: Ref[list[float]]) -> float:
    return sum(xs) / float(len(xs))
