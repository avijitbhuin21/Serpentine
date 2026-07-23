from serpentine import PyVal, pyval_kind
from serp_tomllib import loads, TOMLDecodeError


def main() -> None:
    doc: str = """
# a serp.toml-ish document
name = "serpentine"
version = "0.5.0"
stars = 128
score = 9.5
active = true
tags = ["fast", "safe", "native"]

[package]
authors = ["one", "two"]
edition = 2026

[package.meta]
'quoted key' = 'literal'
esc = "tab\\there \\u00e9"
neg = -12_000
"""
    data: PyVal = loads(doc)
    print(data)
    print(pyval_kind(data), len(data))
    print(data["name"], data["stars"], data["score"], data["active"])
    print(data["tags"][0], len(data["tags"]))
    print(data["package"]["edition"])
    print(data["package"]["meta"]["quoted key"])
    print(data["package"]["meta"]["esc"])
    print(data["package"]["meta"]["neg"])
    print("package" in data, "nope" in data)
    for k in data["package"]:
        print(k)
    if data["active"]:
        print("active is truthy")
    print(data["tags"] == ["fast", "safe", "native"])

    bad: list[str] = [
        "x =",
        "= 1",
        "x = [1,",
        "[[table]]",
        "x = {a = 1}",
        "x = 0xff",
        'x = "unterminated',
        "x = 1\nx = 2",
        "[a]\n[a.b]\n[a]\nq = 1\n[a]\n",
    ]
    for b in bad:
        try:
            v: PyVal = loads(b)
            print("unexpectedly parsed:", v)
        except TOMLDecodeError as e:
            print(f"rejected: {e}")
    try:
        w: PyVal = loads("y = @")
        print(w)
    except ValueError as e2:
        print(f"as ValueError: {e2}")


if __name__ == "__main__":
    main()
