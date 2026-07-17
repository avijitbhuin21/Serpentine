# serp-reject: SE201 unsupported-feature
"""Reject: try/except is Tier 1 — Tier 0 has only fatal runtime errors (SPEC 11)."""


def main() -> None:
    xs: list[int] = [1]
    try:  # E: SE201
        print(xs[5])
    except IndexError:
        print("caught")


if __name__ == "__main__":
    main()
