from serp_hashlib import sha256, sha1, md5


def main() -> None:
    print(sha256(b"").hexdigest())
    print(sha1(b"").hexdigest())
    print(md5(b"").hexdigest())
    print(sha256(b"abc").hexdigest())
    print(sha1(b"abc").hexdigest())
    print(md5(b"abc").hexdigest())
    print(sha256(b"The quick brown fox jumps over the lazy dog").hexdigest())
    s: str = "h\u00e9llo w\u00f6rld \u20ac snake \U0001f40d"
    print(sha256(s.encode()).hexdigest())
    print(sha1(s.encode()).hexdigest())
    print(md5(s.encode()).hexdigest())
    h = sha256()
    h.update(b"hello ")
    h.update(b"world")
    print(h.hexdigest())
    print(h.hexdigest() == sha256(b"hello world").hexdigest())
    d: bytes = sha256(b"abc").digest()
    print(len(d))
    print(d.hex())
    h2 = sha1(b"abc")
    h3 = h2.copy()
    h3.update(b"def")
    print(h2.hexdigest() == sha1(b"abc").hexdigest())
    print(h3.hexdigest() == sha1(b"abcdef").hexdigest())
    big = sha256()
    i: int = 0
    while i < 1000:
        big.update(b"chunk-data-0123456789")
        i += 1
    print(big.hexdigest())
    print(len(md5(b"x").digest()))
    print(len(sha1(b"x").digest()))


if __name__ == "__main__":
    main()
