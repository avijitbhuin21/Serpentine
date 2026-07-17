# serp-reject: SE201 unsupported-feature
"""Reject: return inside a try that has a finally (would skip/swallow cleanup)."""


def f(n: int) -> int:
    try:
        return n  # E: SE201
    finally:
        print("cleanup")


def main() -> None:
    print(f(1))


if __name__ == "__main__":
    main()
