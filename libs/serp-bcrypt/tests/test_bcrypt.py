from serp_bcrypt import gensalt, hashpw, checkpw


def main() -> None:
    fixed: list[bytes] = [b"$2b$04$C5K1/0t0D0H5nAqTbZiSpu", b"$2a$05$CCCCCCCCCCCCCCCCCCCCC.",
                          b"$2y$04$abcdefghijklmnopqrstuu"]
    pws: list[bytes] = [b"", b"U*U", b"correct horse battery staple", "pässwörd".encode("utf-8"),
                        b"a" * 72, b"a" * 72 + b"ignored-after-72"]
    for salt in fixed:
        for pw in pws:
            h: bytes = hashpw(pw, salt)
            print(h.decode("utf-8"), checkpw(pw, h))
    print(hashpw(b"U*U", b"$2a$05$CCCCCCCCCCCCCCCCCCCCC.E5YPO9kmyuRGyh0XouQYb4YMJKvyOeW"))
    print(checkpw(b"U*U", b"$2a$05$CCCCCCCCCCCCCCCCCCCCC.E5YPO9kmyuRGyh0XouQYb4YMJKvyOeW"))
    print(checkpw(b"U*V", b"$2a$05$CCCCCCCCCCCCCCCCCCCCC.E5YPO9kmyuRGyh0XouQYb4YMJKvyOeW"))

    s: bytes = gensalt(4)
    print(len(s), s[:7])
    hashed: bytes = hashpw(b"secret", s)
    print(len(hashed), checkpw(b"secret", hashed), checkpw(b"Secret", hashed))
    print(gensalt()[:7], gensalt(prefix=b"2a")[:7])
    for bad in [b"", b"$2b$04$short", b"$3b$04$C5K1/0t0D0H5nAqTbZiSpu", b"$2b$03$C5K1/0t0D0H5nAqTbZiSpu",
                b"$2b$04$C5K1/0t0D0H5nAqTbZiS!u"]:
        try:
            print(hashpw(b"pw", bad))
        except ValueError as e:
            print("caught:", e)
    try:
        gensalt(3)
    except ValueError as e2:
        print("caught:", e2)
    try:
        gensalt(4, b"2x")
    except ValueError as e3:
        print("caught:", e3)


if __name__ == "__main__":
    main()
