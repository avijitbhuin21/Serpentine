"""Accept: non-Copy str ternary whose arms are a multi-return call and a str() conversion."""
from serpentine import PyVal, Ref


def has(meta: PyVal, key: str) -> bool:
    """True when the PyVal dict carries the key."""
    for k in meta:
        if str(k) == key:
            return True
    return False


def output_key(f: PyVal) -> str:
    """Serialized key for a field: serialization alias, then alias, then name."""
    meta: PyVal = f["meta"]
    if has(meta, "serialization_alias"):
        return str(meta["serialization_alias"])
    if has(meta, "alias"):
        return str(meta["alias"])
    return str(f["name"])


def label(n: int) -> str:
    """A freshly allocated str for the call arm."""
    return "item-" + str(n)


def render(fields: PyVal, by_alias: bool) -> dict[str, int]:
    """Map each field's chosen key to its position."""
    out: dict[str, int] = {}
    i: int = 0
    for f in fields:
        key: str = output_key(f) if by_alias else str(f["name"])
        out[key] = i
        i += 1
    return out


def alternate(fields: PyVal, rounds: int) -> int:
    """Flip ternary arms every iteration so each arm's temps are live on alternate passes."""
    total: int = 0
    i: int = 0
    while i < rounds:
        for f in fields:
            key: str = output_key(f) if i % 2 == 0 else str(f["name"])
            total += len(key)
            wide: str = label(i) + "-with-a-heap-sized-suffix" if i % 3 == 0 else str(f["name"]) + "-" + str(i)
            total += len(wide)
        i += 1
    return total


def stress(fields: PyVal, rounds: int) -> list[str]:
    """Keep same-sized live strings around so a stale temp drop would corrupt them."""
    keep: list[str] = []
    i: int = 0
    while i < rounds:
        for f in fields:
            key: str = output_key(f) if i % 2 == 0 else str(f["name"])
            keep.append(str(f["name"]) + str(i % 10))
            keep.append(key + "#")
        i += 1
    return keep


def fingerprint(keep: Ref[list[str]]) -> str:
    """Stable summary of every kept string: total length, a checksum and samples."""
    size: int = 0
    acc: int = 0
    for s in keep:
        size += len(s)
        for ch in s:
            acc = (acc * 31 + ord(ch)) % 1000000007
    return str(len(keep)) + " " + str(size) + " " + str(acc) + " " + keep[0] + " " + keep[len(keep) - 1]


def main() -> None:
    fields: PyVal = [
        {"name": "user_identifier_long_enough_for_heap", "meta": {"alias": "userIdentifierAliasLongEnough"}},
        {"name": "created_timestamp_long_enough_for_heap",
         "meta": {"serialization_alias": "createdAtSerializedLongEnough", "alias": "c"}},
        {"name": "plain_field_name_long_enough_for_heap", "meta": {}},
    ]
    print(alternate(fields, 3000))
    kept: list[str] = stress(fields, 400)
    print(fingerprint(kept))
    total: int = 0
    j: int = 0
    while j < 200:
        a: dict[str, int] = render(fields, True)
        b: dict[str, int] = render(fields, False)
        total += len(a) + len(b)
        j += 1
    print(render(fields, True))
    print(render(fields, False))
    print(total)
    parts: list[str] = []
    for n in range(6):
        parts.append(label(n) if n % 2 == 0 else str(n * 10))
    print(parts)
    s: str = "fallback"
    t: str = s if len(parts) > 10 else label(len(parts)) + "!"
    print(t, s)


if __name__ == "__main__":
    main()
