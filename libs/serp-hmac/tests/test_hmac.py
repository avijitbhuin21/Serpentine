from serp_hmac import HMAC, new, digest, compare_digest
from serp_hashlib import pbkdf2_hmac


def main() -> None:
    key: bytes = b"\x0b" * 20
    m: HMAC = new(key, b"Hi There", "sha256")
    print(m.hexdigest())
    print(m.name, m.digest_size, m.block_size)
    print(new(b"Jefe", b"what do ya want for nothing?", "sha256").hexdigest())
    long_key: bytes = b"\xaa" * 131
    print(new(long_key, b"Test Using Larger Than Block-Size Key - Hash Key First",
              "sha256").hexdigest())
    inc: HMAC = new(b"Jefe", None, "SHA256")
    inc.update(b"what do ya want ")
    snap: HMAC = inc.copy()
    inc.update(b"for nothing?")
    print(inc.hexdigest())
    print(snap.hexdigest() != inc.hexdigest())
    print(new(b"key", b"The quick brown fox jumps over the lazy dog", "sha1").hexdigest())
    print(new(b"key", b"The quick brown fox jumps over the lazy dog", "md5").hexdigest())
    print(digest(b"k", b"m", "sha256").hex())
    print(new(b"", b"", "sha256").hexdigest())

    print(compare_digest(b"abc", b"abc"), compare_digest(b"abc", b"abd"),
          compare_digest(b"abc", b"abcd"), compare_digest(b"", b""))
    try:
        new(b"k", b"m")
    except TypeError as e:
        print("caught:", e)
    try:
        new(b"k", b"m", "sha3_999")
    except ValueError as e2:
        print("caught:", e2)

    print(pbkdf2_hmac("sha1", b"password", b"salt", 1, 20).hex())
    print(pbkdf2_hmac("sha1", b"password", b"salt", 2, 20).hex())
    print(pbkdf2_hmac("sha1", b"password", b"salt", 4096, 20).hex())
    print(pbkdf2_hmac("sha256", b"password", b"salt", 4096).hex())
    print(pbkdf2_hmac("sha256", b"passwordPASSWORDpassword",
                      b"saltSALTsaltSALTsaltSALTsaltSALTsalt", 4096, 40).hex())
    print(len(pbkdf2_hmac("sha256", b"pw", b"salt", 100000)))
    try:
        pbkdf2_hmac("sha256", b"pw", b"salt", 0)
    except ValueError as e3:
        print("caught:", e3)
    try:
        pbkdf2_hmac("sha256", b"pw", b"salt", 1, 0)
    except ValueError as e4:
        print("caught:", e4)


if __name__ == "__main__":
    main()
