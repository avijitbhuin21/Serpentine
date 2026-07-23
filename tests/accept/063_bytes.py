"""bytes + bytearray + binary file IO: literals, methods, ops, encode/decode."""
import sys


def main() -> None:
    data: bytes = b"hello world"
    print(data)
    print(len(data))
    print(data[0], data[-1])
    print(data[0:5])
    print(data + b"!" * 3)
    print(data.upper())
    print(b"  padded  ".strip())
    print(data.find(b"world"), data.count(b"l"))
    print(data.startswith(b"hell"), data.endswith(b"d"))
    print(data.replace(b"world", b"serpentine"))
    print(data.split(b" "))
    print(b"-".join([b"a", b"b", b"c"]))
    print(b"world" in data, b"nope" in data)
    print(data.hex())
    print(bytes.fromhex("68690a"))
    print(data == b"hello world", data < b"zzz")

    s: str = "snake: \u00e9"
    enc: bytes = s.encode("utf-8")
    print(enc)
    print(enc.decode("utf-8"))
    try:
        print(b"\xff\xfe".decode("utf-8"))
    except UnicodeDecodeError as e:
        print("caught:", e)
    except ValueError as e:
        print("unreachable:", e)

    total: int = 0
    for bv in b"abc":
        total = total + bv
    print(total)

    ba: bytearray = bytearray(b"abc")
    print(ba)
    ba.append(100)
    ba.extend(b"ef")
    ba[0] = 65
    print(ba, len(ba), ba[1])
    print(ba.hex(), ba.decode("utf-8"))
    print(bytes(ba))
    print(bytearray(3), bytes(2))
    vals: list[int] = [104, 105]
    print(bytes(vals), bytearray(vals))

    path: str = "tmp_serp_063.bin"
    with open(path, "wb") as f:
        n: int = f.write(b"\x00\x01binary\xff")
        print(n)
    with open(path, "rb") as g:
        raw: bytes = g.read()
        print(raw)
        print(raw.hex())

    try:
        bad: bytes = bytes([300])
        print(bad)
    except ValueError as e:
        print("range:", e)

    print("done")


if __name__ == "__main__":
    main()
