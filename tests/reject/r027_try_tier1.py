# serp-reject: SE201 unsupported-feature
"""Reject: try/else is not Tier 1 — only try/except/finally is supported."""


def main() -> None:
    xs: list[int] = [1]
    try:  # E: SE201
        print(xs[0])
    except IndexError:
        print("caught")
    else:
        print("no error")


if __name__ == "__main__":
    main()
