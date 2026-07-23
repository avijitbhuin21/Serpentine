# serp-uuid

`uuid4()` for Serpentine ([R] runtime-backed): native builds draw 16 bytes
from the OS CSPRNG (BCryptGenRandom on Windows, /dev/urandom elsewhere) and
format an RFC 4122 version-4 UUID; under CPython this package delegates to
stdlib `uuid`.

## API

- `uuid4() -> str` — e.g. `"f47ac10b-58cc-4372-a567-0e02b2c3d479"`.

## Install

```
serp add serp-uuid
pip install serp-uuid
```
