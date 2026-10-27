from serpentine import PyVal
from serp_jwt import (encode, decode, get_unverified_header, PyJWTError, InvalidTokenError,
                      DecodeError, InvalidSignatureError, ExpiredSignatureError,
                      InvalidAudienceError, InvalidIssuerError, ImmatureSignatureError,
                      InvalidAlgorithmError)
from serp_time import time


def expect_fail(token: str, key: str, label: str) -> None:
    """Decode a token that must be rejected and print the error class and message."""
    try:
        decode(token, key, algorithms=["HS256"])
        print(label, "unexpectedly accepted")
    except InvalidSignatureError as e:
        print(label, "InvalidSignatureError:", e)
    except DecodeError as e2:
        print(label, "DecodeError:", e2)
    except ExpiredSignatureError as e3:
        print(label, "ExpiredSignatureError:", e3)
    except ImmatureSignatureError as e4:
        print(label, "ImmatureSignatureError:", e4)
    except InvalidAudienceError as e5:
        print(label, "InvalidAudienceError:", e5)
    except InvalidTokenError as e6:
        print(label, "InvalidTokenError:", e6)


def main() -> None:
    tok: str = encode({"some": "payload"}, "secret", algorithm="HS256")
    print(tok)
    print(decode(tok, "secret", algorithms=["HS256"]))
    print(get_unverified_header(tok))

    now: int = int(time())
    live: str = encode({"sub": "42", "name": "Ada", "admin": True, "iat": now,
                        "exp": now + 3600, "nbf": now - 10, "roles": ["a", "b"]}, "k3y")
    claims: PyVal = decode(live, "k3y", algorithms=["HS256"])
    print(claims["sub"], claims["name"], claims["admin"], claims["roles"])
    print(int(claims["exp"]) - int(claims["iat"]))

    expect_fail(tok, "wrong", "bad key")
    parts: list[str] = tok.split(".")
    expect_fail(parts[0] + "." + parts[1], "secret", "two segments")
    expect_fail(parts[0] + ".e30." + parts[2], "secret", "swapped payload")
    expect_fail("@@@." + parts[1] + "." + parts[2], "secret", "garbage header")
    expect_fail(encode({"exp": now - 5}, "s"), "s", "expired")
    expect_fail(encode({"nbf": now + 3600}, "s"), "s", "immature")
    expect_fail(encode({"exp": "soon"}, "s"), "s", "string exp")
    expect_fail(encode({"aud": "svc"}, "s"), "s", "aud without audience")

    try:
        decode(encode({"exp": now - 5}, "s"), "s", algorithms=["HS256"], leeway=60)
        print("leeway ok")
    except PyJWTError as e:
        print("leeway failed:", e)
    aud_tok: str = encode({"aud": ["svc", "web"], "iss": "auth.example"}, "s")
    print(decode(aud_tok, "s", algorithms=["HS256"], audience="web", issuer="auth.example"))
    try:
        decode(aud_tok, "s", algorithms=["HS256"], audience="cli")
    except InvalidAudienceError as e7:
        print("aud:", e7)
    try:
        decode(aud_tok, "s", algorithms=["HS256"], audience="web", issuer="evil")
    except InvalidIssuerError as e8:
        print("iss:", e8)
    try:
        decode(tok, "secret", algorithms=["HS512"])
    except InvalidAlgorithmError as e9:
        print("alg:", e9)
    try:
        decode(tok, "secret")
    except DecodeError as e10:
        print("no algorithms:", e10)
    try:
        encode({"a": 1}, "s", algorithm="RS256")
    except NotImplementedError as e11:
        print("encode alg:", e11)
    try:
        encode([1, 2], "s")
    except TypeError as e12:
        print("payload:", e12)


if __name__ == "__main__":
    main()
