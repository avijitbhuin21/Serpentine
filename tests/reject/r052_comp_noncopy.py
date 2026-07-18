# serp-reject: SE003 implicit-transfer
"""Reject: a comprehension may not copy non-Copy elements out of a container."""


def main() -> None:
    rows: list[list[int]] = [[1, 2], [3]]
    dup: list[list[int]] = [row for row in rows]  # E: SE003
    print(len(dup))


if __name__ == "__main__":
    main()
