"""PyVal dicts with non-str keys (int / float / bool), Python hash semantics (1 == 1.0 == True),
JSON key coercion, iteration and membership."""
from __future__ import annotations
from serpentine import PyVal, pyval_json, pyval_kind


def lookup(d: PyVal, k: PyVal) -> PyVal:
    if k in d:
        return d[k]
    return None


def main() -> None:
    d: PyVal = {1: "one", 2: "two", 10: "ten"}
    print(d, len(d), pyval_kind(d))
    print(d[1], d[10], lookup(d, 2), lookup(d, 3), lookup(d, 1.0), lookup(d, True))
    print(2 in d, 3 in d, "1" in d)
    for k in d:
        print(k, pyval_kind(k), d[k])
    f: PyVal = {0.5: "half", 2.0: "two"}
    print(f, f[0.5], f[2], lookup(f, 2.0))
    b: PyVal = {True: "yes", False: "no"}
    print(b, b[True], lookup(b, 1), lookup(b, 0))
    typed: dict[int, str] = {3: "c", 1: "a"}
    p: PyVal = typed
    print(p, p[3], 1 in p)
    nested: PyVal = {"outer": {7: [1, 2]}, "five": {"k": 1.5}}
    print(nested, nested["outer"][7], nested["five"]["k"])
    print(pyval_json(d, True, True), pyval_json(f, True, False), pyval_json(b, True, True))
    plain: PyVal = {"s": 1}
    print(pyval_json(plain, True, True), pyval_json(nested, True, True))
    alt: PyVal = {1.0: "one", 2.0: "two", 10.0: "ten"}
    print(d == {1: "one", 2: "two", 10: "ten"}, d == {1: "one"}, d == alt)
    try:
        print(d[4])
    except KeyError as e:
        print("KeyError:", e)


if __name__ == "__main__":
    main()
