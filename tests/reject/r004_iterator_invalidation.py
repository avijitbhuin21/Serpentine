# serp-reject: SE004 conflicting-borrow
"""Reject: iterator invalidation — Mut use of the iterable inside its for body (5.4)."""


def main() -> None:
    xs: list[int] = [1, 2, 3]
    for x in xs:
        xs.append(x)  # E: SE004


if __name__ == "__main__":
    main()
