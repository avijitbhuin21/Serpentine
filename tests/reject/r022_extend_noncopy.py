# serp-reject: SE211 extend-non-copy
"""Reject: extend on a non-Copy element type — elements cannot be bulk-copied (7.1)."""


def main() -> None:
    a: list[list[int]] = [[1]]
    b: list[list[int]] = [[2]]
    a.extend(b)  # E: SE211
    print(len(a))


if __name__ == "__main__":
    main()
