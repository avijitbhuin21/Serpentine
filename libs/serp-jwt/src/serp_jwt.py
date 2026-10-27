"""serp-jwt — PyJWT-compatible JSON Web Tokens (HS256) for Serpentine.

`encode(payload, key, algorithm="HS256")` and `decode(token, key, algorithms=[...])`
follow PyJWT 2.x: compact JSON (header keys sorted, payload in insertion order),
unpadded base64url segments, HMAC-SHA256 signatures checked in constant time,
and the registered-claim checks for `exp`, `nbf`, `iat`, `aud` and `iss` with an
optional `leeway` (seconds). Errors use PyJWT's class names and messages.

Caps: only HS256 (HS384/HS512 and RSA/EC algorithms raise NotImplementedError);
the key is a str (UTF-8 encoded); `exp`/`nbf`/`iat` must be ints (PyJWT also
accepts datetimes); `options=`/`require=` are not supported.
"""
from __future__ import annotations
from serpentine import Owned, PyVal, pyval_kind
from serp_json import dumps, loads
from serp_base64 import urlsafe_b64encode, urlsafe_b64decode
from serp_hashlib_core import h_hmac, h_compare
from serp_time import time


class PyJWTError(Exception):
    pass


class InvalidTokenError(PyJWTError):
    pass


class DecodeError(InvalidTokenError):
    pass


class InvalidSignatureError(DecodeError):
    pass


class ExpiredSignatureError(InvalidTokenError):
    pass


class InvalidAudienceError(InvalidTokenError):
    pass


class InvalidIssuerError(InvalidTokenError):
    pass


class InvalidIssuedAtError(InvalidTokenError):
    pass


class ImmatureSignatureError(InvalidTokenError):
    pass


class InvalidAlgorithmError(InvalidTokenError):
    pass


def _b64url(data: bytes) -> str:
    """Unpadded base64url text of data."""
    text: str = urlsafe_b64encode(data).decode("utf-8")
    while text.endswith("="):
        text = text[:len(text) - 1]
    return text


def _unb64url(text: str) -> bytes:
    """Decode unpadded base64url text, raising DecodeError on garbage."""
    pad: str = ""
    while (len(text) + len(pad)) % 4 != 0:
        pad = pad + "="
    try:
        return urlsafe_b64decode((text + pad).encode("utf-8"))
    except ValueError as e:
        raise DecodeError("Invalid header padding")


def _sign(alg: str, key: str, signing_input: str) -> bytes:
    """Signature bytes for a supported algorithm."""
    if alg == "HS256":
        return h_hmac("sha256", key.encode("utf-8"), signing_input.encode("utf-8"))
    raise NotImplementedError("Algorithm not supported")


def encode(payload: PyVal, key: str, algorithm: str = "HS256") -> str:
    """Encode a JSON-object payload as a signed compact JWT."""
    if pyval_kind(payload) != "dict":
        raise TypeError("Expecting a dict object, as JWT only supports JSON objects as payloads.")
    if algorithm != "HS256":
        raise NotImplementedError("Algorithm not supported")
    header: str = dumps({"alg": algorithm, "typ": "JWT"}, sort_keys=True, compact=True)
    body: str = dumps(payload, compact=True)
    signing_input: str = _b64url(header.encode("utf-8")) + "." + _b64url(body.encode("utf-8"))
    return signing_input + "." + _b64url(_sign(algorithm, key, signing_input))


def _segments(token: str) -> list[str]:
    """Split a compact JWT into its three segments."""
    parts: list[str] = token.split(".")
    if len(parts) != 3:
        raise DecodeError("Not enough segments")
    return parts


def _json_segment(seg: str, what: str) -> PyVal:
    """Decode one base64url JSON segment that must hold an object."""
    raw: bytes = _unb64url(seg)
    text: str = ""
    try:
        text = raw.decode("utf-8")
    except ValueError as e:
        raise DecodeError(f"Invalid {what} string: must be a json object")
    obj: PyVal = None
    try:
        obj = loads(text)
    except ValueError as e2:
        raise DecodeError(f"Invalid {what} string: must be a json object")
    if pyval_kind(obj) != "dict":
        raise DecodeError(f"Invalid {what} string: must be a json object")
    return obj


def get_unverified_header(token: str) -> PyVal:
    """The token's header object, without verifying anything."""
    parts: list[str] = _segments(token)
    return _json_segment(parts[0], "header")


def _int_claim(payload: PyVal, name: str, label: str) -> int:
    """Read an integer registered claim or raise PyJWT's DecodeError."""
    v: PyVal = payload[name]
    if pyval_kind(v) != "int":
        raise DecodeError(f"{label} claim ({name}) must be an integer.")
    return int(v)


def _check_claims(payload: PyVal, leeway: int, audience: str | None, issuer: str | None) -> None:
    """Validate exp/nbf/iat/aud/iss the way PyJWT does by default."""
    now: int = int(time())
    if "iat" in payload:
        iat: PyVal = payload["iat"]
        if pyval_kind(iat) != "int":
            raise InvalidIssuedAtError("Issued At claim (iat) must be an integer.")
    if "nbf" in payload:
        nbf: int = _int_claim(payload, "nbf", "Not Before")
        if nbf > now + leeway:
            raise ImmatureSignatureError("The token is not yet valid (nbf)")
    if "exp" in payload:
        exp: int = _int_claim(payload, "exp", "Expiration Time")
        if exp <= now - leeway:
            raise ExpiredSignatureError("Signature has expired")
    if audience is None:
        if "aud" in payload:
            raise InvalidAudienceError("Invalid audience")
    else:
        if "aud" not in payload:
            raise InvalidAudienceError("Token is missing the \"aud\" claim")
        aud: PyVal = payload["aud"]
        kind: str = pyval_kind(aud)
        if kind == "str":
            if str(aud) != audience:
                raise InvalidAudienceError("Audience doesn't match")
        elif kind == "list":
            found: bool = False
            for a in aud:
                if pyval_kind(a) != "str":
                    raise InvalidAudienceError("Invalid claim format in token")
                if str(a) == audience:
                    found = True
            if not found:
                raise InvalidAudienceError("Audience doesn't match")
        else:
            raise InvalidAudienceError("Invalid claim format in token")
    if issuer is not None:
        if "iss" not in payload:
            raise InvalidIssuerError("Token is missing the \"iss\" claim")
        if pyval_kind(payload["iss"]) != "str" or str(payload["iss"]) != issuer:
            raise InvalidIssuerError("Invalid issuer")


def decode(jwt: str, key: str, algorithms: Owned[list[str] | None] = None, leeway: int = 0,
           audience: str | None = None, issuer: str | None = None) -> PyVal:
    """Verify a compact JWT's signature and registered claims; return its payload."""
    if algorithms is None:
        raise DecodeError('It is required that you pass in a value for the "algorithms" '
                          'argument when calling decode().')
    parts: list[str] = _segments(jwt)
    header: PyVal = _json_segment(parts[0], "header")
    if "alg" not in header or pyval_kind(header["alg"]) != "str":
        raise InvalidAlgorithmError("The specified alg value is not allowed")
    alg: str = str(header["alg"])
    if alg not in algorithms:
        raise InvalidAlgorithmError("The specified alg value is not allowed")
    if alg != "HS256":
        raise NotImplementedError("Algorithm not supported")
    payload: PyVal = _json_segment(parts[1], "payload")
    sig: bytes = _unb64url(parts[2])
    expected: bytes = _sign(alg, key, parts[0] + "." + parts[1])
    if not h_compare(sig, expected):
        raise InvalidSignatureError("Signature verification failed")
    _check_claims(payload, leeway, audience, issuer)
    return payload
