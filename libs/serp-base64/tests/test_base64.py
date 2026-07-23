from serp_base64 import (b64encode, b64decode, standard_b64encode, standard_b64decode,
                         urlsafe_b64encode, urlsafe_b64decode, b32encode, b32decode,
                         b16encode, b16decode)


def main() -> None:
    print(b64encode(b""))
    print(b64encode(b"f"))
    print(b64encode(b"fo"))
    print(b64encode(b"foo"))
    print(b64encode(b"foobar"))
    print(b64encode(b"hello world"))
    print(b64decode(b"aGVsbG8gd29ybGQ="))
    print(b64decode(b64encode(b"any carnal pleasure.")))
    print(standard_b64encode(b"\xfb\xff"))
    print(urlsafe_b64encode(b"\xfb\xff"))
    print(urlsafe_b64decode(urlsafe_b64encode(b"\xfb\xff\x00\x01")))
    print(b64encode(b"\xfb\xff", b"-_"))
    print(b64decode(b"-_-_", b"-_"))
    print(b64decode(b"aGVs\nbG8=", validate=False))
    print(b32encode(b""))
    print(b32encode(b"f"))
    print(b32encode(b"fo"))
    print(b32encode(b"foobar"))
    print(b32decode(b"MZXW6YTBOI======"))
    print(b32decode(b"mzxw6ytboi======", casefold=True))
    print(b16encode(b""))
    print(b16encode(b"\x01\xab\xcd"))
    print(b16decode(b"01ABCD"))
    print(b16decode(b"01abcd", casefold=True))
    ok: bool = True
    i: int = 0
    data: list[int] = []
    while i < 256:
        data.append(i)
        i += 1
    blob: bytes = bytes(data)
    if b64decode(b64encode(blob)) != blob:
        ok = False
    if b32decode(b32encode(blob)) != blob:
        ok = False
    if b16decode(b16encode(blob)) != blob:
        ok = False
    print(ok)
    try:
        print(b64decode(b"aGVs\nbG8=", validate=True))
    except ValueError as e:
        print("caught:", e)
    try:
        print(b64decode(b"abc"))
    except ValueError as e2:
        print("caught:", e2)
    try:
        print(b16decode(b"01abcd"))
    except ValueError as e3:
        print("caught:", e3)
    try:
        print(b32decode(b"MZXW6YTBOI"))
    except ValueError as e4:
        print("caught:", e4)


if __name__ == "__main__":
    main()
