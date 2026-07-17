# serp-reject: SE203 missing-annotation
"""Reject: unannotated function parameter — signatures are the inference boundary (2.3)."""


def double(x) -> int:  # E: SE203
    return x * 2


def main() -> None:
    print(double(21))


if __name__ == "__main__":
    main()
