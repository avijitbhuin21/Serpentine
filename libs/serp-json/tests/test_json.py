from serpentine import PyVal, pyval_kind
from serp_json import loads, dumps


def main() -> None:
    docs: list[str] = [
        "null",
        "[1, 2.5, -3, 1e3]",
        '  {"name": "serpentine", "tags": ["fast", "safe"], "stars": 128}  ',
        '{"escaped": "line\\nbreak \\u0041\\u00e9 \\ud83d\\ude00", "empty": [], "obj": {"deep": [true, false, null]}}',
        '"just a string"',
        "true",
        "-0.5e-2",
    ]
    for doc in docs:
        v: PyVal = loads(doc)
        print(pyval_kind(v))
        print(dumps(v))
    bad: list[str] = ['{"open": ', "[1, 2", '"unterminated', "01x", "", "[1,]",
                      '{"a" 1}', "{1: 2}", '[1, 2]x', '"bad \\q escape"']
    for doc2 in bad:
        try:
            w: PyVal = loads(doc2)
            print("unexpectedly parsed:", dumps(w))
        except ValueError as e:
            print(f"rejected: {e}")

    data: PyVal = loads('{"a": [1, {"b": "c"}], "d": 2.5, "ok": true}')
    print(data["a"][1]["b"], data["d"], data["ok"] == True)
    print(len(data), "a" in data, "z" in data)
    for k in data:
        print(k)
    if data["ok"]:
        print("truthy")
    print(int(data["a"][0]) + 1, float(data["d"]) * 2.0)

    print(dumps({"z": 1, "a": [True, None, "x"]}))
    print(dumps({"z": 1, "a": 2}, sort_keys=True))
    print(dumps("héllo\n"))
    print(dumps("héllo", ensure_ascii=False))
    print(dumps([1.5, -0.25, 1e300]))
    round1: PyVal = loads('{"a": [1, {"b": "c"}], "d": 2.5}')
    text: str = dumps(round1)
    round2: PyVal = loads(text)
    print(dumps(round2) == text)


if __name__ == "__main__":
    main()
