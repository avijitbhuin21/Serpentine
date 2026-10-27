# serpentine-lang

The Serpentine compiler and `serp` CLI. Serpentine compiles a **statically typed,
ownership-disciplined subset of Python** ahead of time to native machine code with no garbage
collector and no libpython, while the exact same file still runs under CPython.

> **Status: experimental (`0.x`).** Good for tools, demos and internal services; see the
> [readiness checklist](https://github.com/avijitbhuin21/Serpentine/blob/master/docs/readiness.md)
> before using it for internet-facing production work.

## Requirements

- Python 3.11+ (`pip install serpentine-lang` brings `llvmlite`, `uv` and `serpentine-shim`).
- A Rust toolchain (`rustc`) from [rustup.rs](https://rustup.rs). On Windows also the MSVC C++
  Build Tools; on Linux/macOS a C compiler (`cc`).

## Quick start

```console
pip install serpentine-lang
serp new myapp
cd myapp
serp run                 # build (LLVM, debug) + run
serp build main.py       # optimized native binary (release builds are re-validated by rustc)
serp add serp-json       # add a Serpentine library from PyPI (pinned in serp.lock)
serp check main.py       # type + ownership diagnostics only
```

```python
from serpentine import Ref


def mean(xs: Ref[list[float]]) -> float:
    return sum(xs) / len(xs)


def main() -> None:
    temps: list[float] = [21.5, 23.0, 19.25]
    print(f"mean {mean(temps):.2f}")


if __name__ == "__main__":
    main()
```

`int`/`float`/`str`/`bool` need no annotations; list, dict and object parameters state a
convention (`Ref`, `Mut` or `Owned`).

## What compiles

Typed functions, dataclasses (single inheritance), unions/`Optional`, generics and protocols,
exceptions, f-strings with format specs, comprehensions, lambdas, threads and asyncio. Untyped
code, plain classes with `super()`, generators, `*args`/`**kwargs` and regular PyPI imports are
refused with a hint. Use the `serp-*` libraries instead (`serp-json`, `serp-re`, `serp-venom` for
FastAPI-style services, `serp-molt` for pydantic-style models, and more).

## Commands

| Command | What it does |
|---|---|
| `serp check FILE` | type and ownership checking (no build) |
| `serp build FILE [-o OUT] [--backend llvm\|rust] [--debug]` | native binary |
| `serp run` / `serp test` | build and run the project entry / its `test_*.py` files |
| `serp new NAME` / `serp init` | scaffold a project (`serp.toml`, `main.py`, `.venv`) |
| `serp add PKG` / `serp remove PKG` | manage `serp-*` dependencies (pinned in `serp.lock`) |
| `serp lsp` | language server (diagnostics) for editors |

## Links

- [Repository and README](https://github.com/avijitbhuin21/Serpentine)
- [Language tour](https://github.com/avijitbhuin21/Serpentine/blob/master/docs/language/tour.md)
  and [divergences from CPython](https://github.com/avijitbhuin21/Serpentine/blob/master/docs/language/divergences.md)
- [Library catalogue](https://github.com/avijitbhuin21/Serpentine/blob/master/docs/libraries.md)
- [Changelog](https://github.com/avijitbhuin21/Serpentine/blob/master/CHANGELOG.md)

MIT licensed.
