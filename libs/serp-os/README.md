# serp-os

OS primitives for Serpentine ([R] runtime-backed): native builds call
runtime primitives; under CPython this package delegates to the `os` module.
Error messages are normalized identically on both sides so dual runs stay
byte-identical.

## API

- `getenv(name) -> str` — `""` when unset. `has_env(name) -> bool`.
- `setenv(name, value)` / `unsetenv(name)` — `ValueError` on illegal names.
- `getcwd() -> str`, `chdir(path)`.
- `exists / is_file / is_dir (path) -> bool`.
- `mkdir / rmdir / remove (path)` — single level; normalized
  `FileNotFoundError` / `OSError` messages.
- `listdir(path) -> list[str]` — **always sorted** (determinism contract).

## Install

```
serp add serp-os
pip install serp-os
```
