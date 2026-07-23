from serpentine import move
from serp_structs import (heappush, heappop, heapify, heappushpop, heapreplace,
                          bisect, bisect_left, bisect_right, insort,
                          insort_left, insort_right, Deque, count_items,
                          increment, most_common)


def main() -> None:
    h: list[int] = []
    data: list[int] = [5, 1, 9, 3, 7, 1]
    for v in data:
        heappush(h, v)
    print(h)
    drained: list[int] = []
    while len(h) > 0:
        drained.append(heappop(h))
    print(drained)
    try:
        print(heappop(h))
    except IndexError as e:
        print("caught:", e)
    try:
        print(heapreplace(h, 5))
    except IndexError as e:
        print("caught:", e)
    h2: list[int] = [9, 4, 6, 1, 8, 2]
    heapify(h2)
    print(h2)
    print(heappushpop(h2, 0), heappushpop(h2, 7))
    print(heapreplace(h2, 3))
    print(h2)
    out2: list[int] = []
    while len(h2) > 0:
        out2.append(heappop(h2))
    print(out2)

    xs: list[int] = [1, 3, 3, 5, 8]
    print(bisect_left(xs, 3), bisect_right(xs, 3), bisect(xs, 3))
    print(bisect_left(xs, 0), bisect_right(xs, 99))
    print(bisect_left(xs, 3, 2), bisect_right(xs, 3, 0, 2))
    try:
        print(bisect_left(xs, 3, -1))
    except ValueError as e:
        print("caught:", e)
    insort(xs, 4)
    insort_left(xs, 0)
    insort_right(xs, 3)
    print(xs)

    df: list[str] = []
    db: list[str] = []
    d: Deque[str] = Deque(move(df), move(db))
    d.push_right("b")
    d.push_right("c")
    d.push_left("a")
    print(d.size(), d.is_empty())
    print(d.pop_left())
    print(d.pop_right())
    print(d.pop_right())
    print(d.is_empty())
    try:
        print(d.pop_left())
    except IndexError as e:
        print("caught:", e)

    dif: list[int] = []
    dib: list[int] = []
    di: Deque[int] = Deque(move(dif), move(dib))
    di.push_left(1)
    di.push_left(2)
    di.push_right(3)
    print(di.pop_right(), di.pop_right(), di.pop_right())

    words: list[str] = ["red", "blue", "red", "green", "blue", "red"]
    counts: dict[str, int] = count_items(words)
    print(counts["red"], counts["blue"], counts["green"])
    increment(counts, "blue")
    increment(counts, "yellow", 5)
    print(most_common(counts, 2))
    print(most_common(counts, -1))
    print(most_common(counts, 99))


if __name__ == "__main__":
    main()
