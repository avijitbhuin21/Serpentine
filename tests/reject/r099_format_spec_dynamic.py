# serp-reject: SE201 unsupported-feature
"""Reject: a format spec built from a nested replacement field (dynamic width)."""


def main() -> None:
    width: int = 8
    name: str = "ab"
    print(f"[{name:>{width}}]")  # E: SE201


if __name__ == "__main__":
    main()
