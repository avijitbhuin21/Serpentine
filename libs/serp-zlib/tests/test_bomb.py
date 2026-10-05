from serp_zlib import decompress, inflate


def bomb(k: int) -> bytes:
    """Raw DEFLATE: one literal then 8*k back-references of length 258 (inflates to 1 + 2064*k bytes)."""
    prefix: bytes = bytes([99, 24, 5])
    pattern: bytes = bytes([163, 96, 20, 140, 130, 81, 48, 10, 70, 193, 40, 24, 5])
    suffix: bytes = bytes([163, 96, 20, 140, 130, 81, 48, 10, 70, 193, 40, 0, 0])
    buf: bytearray = bytearray()
    buf.extend(prefix)
    i: int = 1
    while i < k:
        buf.extend(pattern)
        i += 1
    buf.extend(suffix)
    return bytes(buf)


def main() -> None:
    """Small periodic streams inflate normally; a >256 MiB bomb is refused with ValueError."""
    small: bytes = inflate(bomb(5))
    print("small", len(small), small[0], small[len(small) - 1])
    try:
        big: bytes = inflate(bomb(140000))
        print("inflated", len(big))
    except ValueError as e:
        print("raw:", e)
    wrapped: bytearray = bytearray()
    wrapped.extend(bytes([120, 1]))
    wrapped.extend(bomb(140000))
    wrapped.extend(bytes([0, 0, 0, 0]))
    try:
        out: bytes = decompress(bytes(wrapped))
        print("decompressed", len(out))
    except ValueError as e:
        print("zlib:", e)


if __name__ == "__main__":
    main()
