"""Accept: set literals, comprehensions, methods and membership (LB7)."""

from serpentine import Ref


def dedup(words: Ref[list[str]]) -> list[str]:
    """Return the distinct words in sorted order."""
    seen: set[str] = set()
    for w in words:
        seen.add(w)
    return sorted(seen)


def main() -> None:
    nums: set[int] = {3, 1, 2, 3, 1}
    print(len(nums))
    print(1 in nums, 9 in nums, 9 not in nums)
    nums.add(4)
    nums.discard(1)
    nums.remove(2)
    print(sorted(nums))

    other: set[int] = set([3, 4, 5, 5])
    print(sorted(nums.union(other)))
    print(sorted(nums.intersection(other)))
    print(sorted(nums.difference(other)))
    print(sorted(nums.symmetric_difference(other)))
    print(nums.issubset(other), other.issuperset(nums), nums.isdisjoint(other))

    squares: set[int] = {n * n for n in range(6) if n % 2 == 0}
    print(sorted(squares))

    total: int = 0
    for s in squares:
        total += s
    print(total)

    copy: set[int] = squares.copy()
    copy.update(other)
    print(sorted(copy), len(squares))
    copy.difference_update(other)
    print(sorted(copy))
    copy.intersection_update(squares)
    print(sorted(copy))

    words: set[str] = {"b", "a"}
    print(sorted(words), len(words))
    print(dedup(["x", "y", "x"]))

    empty: set[int] = set()
    print(len(empty), sorted(empty))
    frozen: set[str] = frozenset(["p", "q", "p"])
    print(sorted(frozen))

    copy.clear()
    print(len(copy))


if __name__ == "__main__":
    main()
