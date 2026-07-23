from serp_itertools import (accumulate, batched, chain, combinations,
                            combinations_with_replacement, compress, count,
                            cycle, dropwhile, filterfalse, islice, pairwise,
                            permutations, product, repeat, takewhile,
                            zip_longest)


def main() -> None:
    c = count(10, 3)
    print(next(c), next(c), next(c))
    c2 = count()
    print(next(c2), next(c2))
    c3 = count(5)
    for v in islice([0, 0, 0], 0):
        print(v)
    print(next(c3))

    ints: list[int] = [1, 2, 3]
    cy = cycle(ints)
    got: list[int] = []
    k: int = 0
    while k < 7:
        got.append(next(cy))
        k += 1
    print(got)
    none: list[int] = []
    cy2 = cycle(none)
    try:
        print(next(cy2))
    except StopIteration:
        print("cycle empty")

    r = repeat("ab", 3)
    for s in r:
        print(s)
    r2 = repeat(9)
    print(next(r2), next(r2))
    r3 = repeat(7, 0)
    try:
        print(next(r3))
    except StopIteration:
        print("repeat zero")

    a: list[int] = [1, 2, 3]
    b: list[int] = [40, 50]
    for v2 in chain(a, b):
        print(v2)
    words: list[str] = ["x", "y"]
    more: list[str] = ["z"]
    for w in chain(words, more):
        print(w)

    nums: list[int] = [10, 20, 30, 40, 50, 60]
    for v3 in islice(nums, 3):
        print(v3)
    for v4 in islice(nums, 2, 5):
        print(v4)
    for v5 in islice(nums, 1, -1, 2):
        print(v5)
    for v6 in islice(nums, 4, 99):
        print(v6)
    try:
        bad = islice(nums, 0, -3)
        print(next(bad))
    except ValueError as e:
        print("caught:", e)
    try:
        bad2 = islice(nums, 1, 4, 0)
        print(next(bad2))
    except ValueError as e2:
        print("caught:", e2)

    flags: list[bool] = [True, False, True, False, True, True]
    for v7 in compress(nums, flags):
        print(v7)
    short: list[bool] = [False, True]
    for v8 in compress(nums, short):
        print(v8)

    for v9 in accumulate(nums):
        print(v9)
    fs: list[float] = [0.5, 1.5, 2.0]
    for f in accumulate(fs):
        print(f)
    parts: list[str] = ["a", "b", "c"]
    for s2 in accumulate(parts):
        print(s2)
    for v10 in accumulate(none):
        print(v10)
    print("accumulate empty ok")

    for pa, pb in pairwise(nums):
        print(pa, pb)
    single: list[int] = [1]
    for pc, pd in pairwise(single):
        print(pc, pd)
    print("pairwise single ok")

    for qa, qb in product(a, b):
        print(qa, qb)
    strs2: list[str] = ["u", "v"]
    for qc, qd in product(words, strs2):
        print(qc, qd)

    for za, zb in zip_longest(a, b, 0):
        print(za, zb)
    for zc, zd in zip_longest(words, more, "-"):
        print(zc, zd)

    tw = takewhile(lambda x: x < 40, nums)
    for v11 in tw:
        print(v11)
    try:
        print(next(tw))
    except StopIteration:
        print("takewhile done")
    for v12 in dropwhile(lambda x: x < 40, nums):
        print(v12)
    for v13 in filterfalse(lambda x: x % 20 == 0, nums):
        print(v13)
    for s3 in takewhile(lambda s: len(s) == 1, words):
        print(s3)

    for row in batched(nums, 2):
        print(row)
    for row2 in batched(nums, 4):
        print(row2)
    try:
        bad3 = batched(nums, 0)
        print(next(bad3))
    except ValueError as e3:
        print("caught:", e3)

    abc: list[str] = ["A", "B", "C"]
    for row3 in permutations(abc):
        print(row3)
    for row4 in permutations(abc, 2):
        print(row4)
    four: list[int] = [1, 2, 3, 4]
    for row5 in permutations(four, 1):
        print(row5)
    for row6 in permutations(abc, 0):
        print(row6)
    for row7 in permutations(abc, 9):
        print(row7)
    print("permutations big-r ok")

    for row8 in combinations(four, 2):
        print(row8)
    for row9 in combinations(abc, 3):
        print(row9)
    for row10 in combinations(abc, 0):
        print(row10)
    for row11 in combinations_with_replacement(abc, 2):
        print(row11)
    for row12 in combinations_with_replacement(four, 1):
        print(row12)

    total: int = 0
    for v14 in chain(a, b):
        if v14 == 2:
            continue
        total += v14
        if v14 == 40:
            break
    print("total", total)


if __name__ == "__main__":
    main()
