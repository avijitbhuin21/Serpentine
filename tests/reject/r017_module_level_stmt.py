# serp-reject: SE205 module-level-statement
"""Reject: arbitrary module-level statements — imports, defs, constants only (SPEC 9)."""

print("side effect at import time")  # E: SE205


def main() -> None:
    print("main")


if __name__ == "__main__":
    main()
