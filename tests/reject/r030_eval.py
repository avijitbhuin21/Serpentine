# serp-reject: SE201 unsupported-feature
"""Reject: eval is in the explicitly-never list (1.2)."""


def main() -> None:
    print(eval("1 + 1"))  # E: SE201


if __name__ == "__main__":
    main()
