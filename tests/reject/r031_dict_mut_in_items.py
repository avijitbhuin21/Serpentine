# serp-reject: SE004 conflicting-borrow
"""Reject: writing into a dict while iterating its items — Ref held for the body (5.4)."""


def main() -> None:
    d: dict[str, int] = {"a": 1}
    for k, v in d.items():
        d[k] = v + 1  # E: SE004


if __name__ == "__main__":
    main()
