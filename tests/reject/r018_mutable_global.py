# serp-reject: SE206 mutable-global
"""Reject: non-Copy module-level binding — mutable globals are Tier-0 forbidden (SPEC 9)."""

CACHE: list[int] = [1, 2, 3]  # E: SE206


def main() -> None:
    print(CACHE)


if __name__ == "__main__":
    main()
