# serp-reject: SE214 type-mismatch
"""Reject: set methods are type-checked against the element type (LB7)."""


def main() -> None:
    nums: set[int] = {1, 2}
    nums.add("three")  # E: SE214
    print(len(nums))


if __name__ == "__main__":
    main()
