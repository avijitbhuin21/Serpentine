# serp-hmac

Drop-in replacement for Python's `hmac` module for [Serpentine](https://github.com/avijitbhuin21/Serpentine).

```python
from serp_hmac import new, compare_digest

mac = new(b"secret", b"payload", "sha256")
print(mac.hexdigest())
print(compare_digest(mac.digest(), mac.digest()))
```

Native builds compute HMAC and the constant-time comparison in the Serpentine runtime;
under CPython the same file delegates to the stdlib `hmac`.

Caps: `digestmod` is a name string (`"sha256"`, `"sha1"`, `"md5"`); `compare_digest` takes bytes.
