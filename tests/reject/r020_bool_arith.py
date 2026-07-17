# serp-reject: SE208 bool-arithmetic
"""Reject: bool in an arithmetic position — write int(b) instead (D5)."""


def main() -> None:
    t: bool = True
    print(t + 1)  # E: SE208


if __name__ == "__main__":
    main()
