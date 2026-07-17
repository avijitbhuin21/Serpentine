"""Benchmark: allocation churn — many short-lived lists and class instances.

This is the no-GC dividend workload: every list/object is freed deterministically
at scope end; a tracing/conservative GC pays for the garbage it scans.
"""
from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float

    def energy(self: Ref[Particle]) -> float:
        return 0.5 * (self.vx * self.vx + self.vy * self.vy)


def step(n: int) -> float:
    total: float = 0.0
    for i in range(n):
        xs: list[int] = []
        for j in range(20):
            xs.append(i + j)
        p: Particle = Particle(1.0, 2.0, float(i % 7), float(i % 11))
        total += p.energy() + float(len(xs))
    return total


def main() -> None:
    print(step(300000))


if __name__ == "__main__":
    main()
