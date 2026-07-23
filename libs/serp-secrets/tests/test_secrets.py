from serp_secrets import (token_hex, token_urlsafe, randbelow, token_bytes,
                          randbits, choice, compare_digest, DEFAULT_ENTROPY)


def new_surface() -> None:
    print(len(token_hex()))
    print(len(token_bytes()))
    print(len(token_bytes(8)))
    print(len(token_bytes(0)))
    print(DEFAULT_ENTROPY)
    ok2: bool = True
    for _ in range(100):
        b: int = randbits(8)
        if b < 0 or b > 255:
            ok2 = False
        b2: int = randbits(63)
        if b2 < 0:
            ok2 = False
    print(ok2)
    items: list[str] = ["a", "b", "c"]
    pick: str = choice(items)
    print(pick == "a" or pick == "b" or pick == "c")
    print(compare_digest("abc", "abc"))
    print(compare_digest("abc", "abd"))
    print(compare_digest("abc", "ab"))
    try:
        print(randbits(0))
    except ValueError as e:
        print("caught:", e)
    try:
        print(randbits(64))
    except OverflowError as e2:
        print("caught:", e2)
    try:
        print(token_bytes(-1))
    except ValueError as e3:
        print("caught:", e3)
    empty: list[int] = []
    try:
        print(choice(empty))
    except IndexError as e4:
        print("caught:", e4)

HEX: str = "0123456789abcdef"
URLSAFE: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def all_in(s: str, alphabet: str) -> bool:
    for c in s:
        if alphabet.find(c) < 0:
            return False
    return True


def main() -> None:
    t: str = token_hex(16)
    print(len(t), all_in(t, HEX))
    print(token_hex(0))
    print(token_hex(16) != token_hex(16))
    u: str = token_urlsafe(16)
    print(len(u), all_in(u, URLSAFE))
    u2: str = token_urlsafe(3)
    print(len(u2), all_in(u2, URLSAFE))
    print(token_urlsafe(0))
    ok: bool = True
    counts: dict[int, int] = {}
    for _ in range(200):
        r: int = randbelow(10)
        if r < 0 or r >= 10:
            ok = False
        if r in counts:
            counts[r] += 1
        else:
            counts[r] = 1
    print(ok, len(counts) > 3)
    print(randbelow(1))
    try:
        print(randbelow(0))
    except ValueError as e:
        print("caught:", e)
    try:
        print(token_hex(-1))
    except ValueError as e:
        print("caught:", e)
    try:
        print(token_urlsafe(-5))
    except ValueError as e:
        print("caught:", e)
    new_surface()


if __name__ == "__main__":
    main()
