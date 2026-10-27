# serp-jwt

PyJWT-compatible JSON Web Tokens (HS256) for [Serpentine](https://github.com/avijitbhuin21/Serpentine).

```python
from serp_jwt import encode, decode, ExpiredSignatureError

token = encode({"sub": "42", "exp": 1900000000}, "secret", algorithm="HS256")
claims = decode(token, "secret", algorithms=["HS256"])
```

Tokens are byte-identical to PyJWT 2.x output. `decode` verifies the signature in constant
time and checks `exp`, `nbf`, `iat`, `aud` and `iss` (with `leeway=`, `audience=`, `issuer=`).

Caps: HS256 only; `str` keys; integer time claims.
