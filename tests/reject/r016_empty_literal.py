# serp-reject: SE204 unknown-element-type
"""Reject: empty container literal without an annotation at first initialization (2.3)."""


def main() -> None:
    xs = []  # E: SE204
    xs.append(1)
    print(xs)


if __name__ == "__main__":
    main()
