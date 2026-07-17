# serp-reject: SE210 unnarrowed-optional
"""Reject: narrowing applies to names only, never to indexed places (SPEC 6)."""


def main() -> None:
    xs: list[int | None] = [1, None]
    if xs[0] is not None:
        print(xs[0] + 1)  # E: SE210


if __name__ == "__main__":
    main()
