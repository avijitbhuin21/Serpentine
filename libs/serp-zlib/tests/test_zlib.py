from serp_zlib import (adler32, compress, crc32, decompress, deflate,
                       gzip_compress, gzip_decompress, inflate, MAX_WBITS,
                       DEFLATED, Z_DEFAULT_COMPRESSION, Z_BEST_COMPRESSION,
                       Z_BEST_SPEED, Z_NO_COMPRESSION)


def check_roundtrip(label: str, data: bytes) -> None:
    for level in [0, 1, 6, 9]:
        z: bytes = compress(data, level)
        back: bytes = decompress(z)
        print(label, level, back == data)
    raw: bytes = deflate(data, 6)
    print(label, "raw", inflate(raw) == data)
    gz: bytes = gzip_compress(data, 6)
    print(label, "gzip", gzip_decompress(gz) == data)


def main() -> None:
    print(crc32(b""))
    print(crc32(b"hello world"))
    print(crc32(b"The quick brown fox jumps over the lazy dog"))
    print(adler32(b""))
    print(adler32(b"hello world"))
    print(adler32(b"Wikipedia"))

    check_roundtrip("empty", b"")
    check_roundtrip("short", b"hi")
    check_roundtrip("repeat", b"hello hello hello hello hello " * 40)
    vals: list[int] = []
    i: int = 0
    while i < 256:
        vals.append(i)
        i += 1
    allbytes: bytes = bytes(vals)
    check_roundtrip("binary", allbytes * 5)

    zfix: bytes = bytes.fromhex("78da2bc94855282ccd4cce56482aca2fcf5348cbaf50c82acd2d2856c82f4b2d5228014ae72456552aa4e4a7eb8179a38ac9520c002fc08239")
    plain: bytes = decompress(zfix)
    print(len(plain))
    print(plain[0:44])
    print(crc32(plain))
    print(crc32(b"world", crc32(b"hello ")) == crc32(b"hello world"))
    print(adler32(b"world", adler32(b"hello ")) == adler32(b"hello world"))
    d1: bytes = compress(b"default level data " * 20)
    print(decompress(d1) == b"default level data " * 20)
    raw2: bytes = deflate(b"wbits routing test " * 10, 6)
    print(decompress(raw2, -15) == b"wbits routing test " * 10)
    gz2: bytes = gzip_compress(b"gz wbits " * 9, 6)
    print(decompress(gz2, wbits=31) == b"gz wbits " * 9)
    print(MAX_WBITS, DEFLATED, Z_DEFAULT_COMPRESSION, Z_BEST_COMPRESSION, Z_BEST_SPEED, Z_NO_COMPRESSION)
    try:
        print(decompress(b"data", 13))
    except ValueError as e0:
        print("caught:", e0)

    gfix: bytes = bytes.fromhex("1f8b080000000000020a2b4e2d2a48cd2bc9cc4b5548afca2c5048cbac28292d4a05001d2649b817000000")
    print(gzip_decompress(gfix))

    try:
        bad: bytes = compress(b"x", 10)
        print(len(bad))
    except ValueError as e:
        print("level:", e)
    try:
        junk: bytes = decompress(b"this is not compressed")
        print(len(junk))
    except ValueError as e:
        print("corrupt:", e)
    try:
        empty: bytes = inflate(b"")
        print(len(empty))
    except ValueError as e:
        print("truncated:", e)
    try:
        notgz: bytes = gzip_decompress(b"\x00\x01\x02")
        print(len(notgz))
    except ValueError as e:
        print("notgzip:", e)

    print("done")


if __name__ == "__main__":
    main()
