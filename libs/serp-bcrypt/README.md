# serp-bcrypt

bcrypt password hashing for [Serpentine](https://github.com/avijitbhuin21/Serpentine), API-compatible with
[pyca/bcrypt](https://pypi.org/project/bcrypt/).

```python
from serp_bcrypt import gensalt, hashpw, checkpw

hashed = hashpw(b"correct horse", gensalt())
assert checkpw(b"correct horse", hashed)
```

Hashes are byte-identical to pyca/bcrypt 4.x (verified against it across `2a`/`2b`, empty, 72-byte and
longer passwords). Native builds run EksBlowfish in the runtime; CPython runs use a pure-Python delegate.
