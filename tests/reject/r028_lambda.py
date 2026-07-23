# serp-reject: SE201 unsupported-feature
"""Reject: a lambda needs an expected Callable type (annotate the target)."""


def main() -> None:
    f = lambda x: x * 2  # E: SE201
    print(f(21))


if __name__ == "__main__":
    main()
