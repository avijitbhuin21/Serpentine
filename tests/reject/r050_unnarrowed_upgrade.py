# serp-reject: SE210 unnarrowed-optional
"""Reject: upgrade() returns Shared[T] | None — narrow before use."""
from serpentine import Shared, Weak, share, downgrade, upgrade, move


def main() -> None:
    xs: list[int] = [1]
    s: Shared[list[int]] = share(move(xs))
    w: Weak[list[int]] = downgrade(s)
    u: Shared[list[int]] | None = upgrade(w)
    print(u[0])  # E: SE210
    print(len(s))


if __name__ == "__main__":
    main()
