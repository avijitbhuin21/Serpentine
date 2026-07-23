"""PyVal: boxed dynamic values — coercion, getitem, truthiness, eq, extraction."""
from serpentine import PyVal, pyval_kind


def describe(v: PyVal) -> str:
    return pyval_kind(v)


def pick(v: PyVal, key: str) -> PyVal:
    return v[key]


def main() -> None:
    a: PyVal = None
    b: PyVal = True
    c: PyVal = 42
    d: PyVal = 2.5
    e: PyVal = "hi"
    print(a, b, c, d, e)
    print(pyval_kind(a), pyval_kind(b), pyval_kind(c), pyval_kind(d), pyval_kind(e))

    xs: PyVal = [1, "two", 3.0, None, True, [10, 20], {"k": "v"}]
    print(xs)
    print(len(xs), pyval_kind(xs))
    print(xs[0], xs[1], xs[5][1], xs[6]["k"])
    print(xs[-1])

    obj: PyVal = {"name": "serpentine", "stars": 128, "tags": ["fast", "safe"],
                  "meta": {"ok": True, "score": 9.5}}
    print(obj)
    print(len(obj), pyval_kind(obj))
    print(obj["name"], obj["stars"], obj["tags"][0], obj["meta"]["score"])
    print(pick(obj, "name"))

    for k in obj:
        print(k, obj[k])
    for item in xs[5]:
        print(item)
    for ch in xs[1]:
        print(ch)

    print("name" in obj, "nope" in obj, "nope" not in obj)
    print(1 in xs, "two" in xs, 99 in xs)

    print(xs[0] == 1, xs[0] == 1.0, xs[0] == True, xs[0] == 2)
    print(xs[1] == "two", xs[3] == None, xs[4] == True)
    print(xs[5] == [10, 20], xs[6] == {"k": "v"}, xs != c)
    other: PyVal = {"stars": 128, "name": "serpentine", "tags": ["fast", "safe"],
                    "meta": {"score": 9.5, "ok": True}}
    print(obj == other)

    if obj["meta"]["ok"]:
        print("truthy dict field")
    empty: PyVal = []
    if not empty:
        print("empty list is falsy")
    zero: PyVal = 0
    print(bool(zero), bool(c), bool(a), bool(e), bool(empty))

    print(int(c), int(b), int(d))
    s_num: PyVal = "123"
    print(int(s_num), float(s_num))
    print(float(c), float(d))
    print(str(c), str(d), str(a), str(e))
    print(f"{c} {e!r} {obj['name']}")

    try:
        bad: PyVal = xs[99]
        print(bad)
    except IndexError as err1:
        print("IndexError:", err1)
    try:
        bad2: PyVal = obj["missing"]
        print(bad2)
    except KeyError as err2:
        print("KeyError:", err2)
    try:
        bad3: PyVal = c[0]
        print(bad3)
    except TypeError as err3:
        print("TypeError:", err3)
    try:
        n: int = int(xs[5])
        print(n)
    except TypeError as err4:
        print("TypeError:", err4)

    nested: list[PyVal] = [c, e, xs[5]]
    print(nested)
    table: dict[str, PyVal] = {"x": 1, "y": "z"}
    print(table)
    print(table["x"], table["y"])


if __name__ == "__main__":
    main()
