# Serpentine

[![CI](https://github.com/avijitbhuin21/Serpentine/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/avijitbhuin21/Serpentine/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/serpentine-lang)](https://pypi.org/project/serpentine-lang/)

> Python source code, written under an ownership-and-borrowing discipline, ahead-of-time
> compiled to native machine code with **no garbage collector** — while the exact same file
> remains valid, runnable CPython. One codebase, two execution modes.

> [!WARNING]
> **Status: experimental (`0.x`).** Fine for hobby projects, demos, benchmarks and internal tools.
> Not yet recommended for internet-facing production services, and there is no compatibility
> promise across `0.x` minor versions ([docs/stability.md](docs/stability.md)). See
> [docs/readiness.md](docs/readiness.md), [CHANGELOG.md](CHANGELOG.md) and [SECURITY.md](SECURITY.md).

**Status:** v0.7: LLVM-direct native builds (default backend) with a rustc oracle pass on release
builds, project tooling (`serp new` / `add` / `run` / `test`), packages, an LSP, 44 `serp-*`
libraries (stdlib, FastAPI-, pydantic-, requests-style drop-ins), and a 112-program dual-run corpus
that is byte-identical on Windows/Linux/macOS. The runtime is fuzzed and sanitizer-tested
(AddressSanitizer + Miri); see the readiness checklist for evidence.

## Is this "compile my Python"? Not quite.

Serpentine compiles a **statically typed subset of Python**. Every program it accepts still runs
unchanged under CPython, but plenty of ordinary Python is refused:

| Compiles | Refused (with a hint explaining the alternative) |
|---|---|
| Typed functions, `int`/`float`/`str`/`bytes`/`list`/`dict`/`set`/tuples, unions, `Optional` | Untyped code and module-level script statements (put them in `main()`) |
| `@dataclass` classes, single inheritance, operators, properties, protocols, generics | Plain classes, `super()` calls, virtual dispatch, metaclasses |
| f-strings with (nearly) the full format mini-language, comprehensions, lambdas, closures over values | Generator expressions, `yield`, `*args` / `**kwargs`, the walrus operator |
| Exceptions, `with`, decorators, threads, asyncio | `import os` / `requests` / any regular PyPI package; use the `serp-*` equivalents (`serp_os`, `serp_fang`, ...) |
| Ownership via `Owned`/`Ref`/`Mut`/`move` (needed only on non-Copy parameters such as lists, dicts and objects) | Aliasing a non-Copy value without `move()` (a compile-time ownership error) |

Details: [docs/guides/migration.md](docs/guides/migration.md) and
[docs/language/divergences.md](docs/language/divergences.md). `int` is a 64-bit integer that traps
on overflow; use `serp-bigint` for arbitrary precision.

## Requirements

- **Python 3.11+** (the shim and CPython runs). CI tests 3.12.
- **Rust toolchain** (`rustc`) from [rustup.rs](https://rustup.rs): native builds link through it and
  release builds re-validate ownership with it.
- **Windows:** the MSVC C++ Build Tools (the linker rustc uses). **Linux/macOS:** a C compiler (`cc`).
- `pip install serpentine-lang` brings everything else (`llvmlite`, `uv`, the shim).

## Quick start

```console
pip install serpentine-lang        # brings llvmlite, uv and the shim along
serp new myapp --git               # scaffold: serp.toml, main.py, .venv (shim installed), git
cd myapp
serp run                           # build (LLVM, debug) + run
serp build main.py                 # native binary (release: O3 + runtime LTO + rustc oracle)
serp add serp-json                 # add a Serpentine library from PyPI (pinned in serp.lock)
```

`serp check` gives ownership/type diagnostics; `serp lsp` serves them to your editor.

Code over `int`/`float`/`str`/`bool` needs no ownership annotations; parameters that take lists,
dicts or objects state how they are passed (`Ref` to borrow, `Mut` to borrow mutably, `Owned` to
take ownership):

```python
from serpentine import Ref


def mean(xs: Ref[list[float]]) -> float:
    return sum(xs) / len(xs)


def main() -> None:
    temps: list[float] = [21.5, 23.0, 19.25]
    print(f"mean {mean(temps):.2f}  max {max(temps):>6.1f}")


if __name__ == "__main__":
    main()
```

Performance depends on the workload: numeric and allocation-heavy kernels run roughly 9-140x
faster than CPython, while string-heavy code is about CPython speed (single Windows machine;
[docs/guides/benchmarks.md](docs/guides/benchmarks.md)).

## The Dual-Execution Guarantee

Any program accepted by `serp check` produces the same observable behavior when
(a) executed by CPython, and (b) compiled by `serp build` and run natively — modulo a small,
explicitly documented list of divergences ([docs/spec.md §10](docs/spec.md)).

```python
from serpentine import Owned, Ref, Mut, move

def total(prices: Ref[list[float]]) -> float:
    return sum(prices)

def main() -> None:
    prices: Owned[list[float]] = [9.99, 4.50]
    print(total(prices))     # immutable borrow, ends after the call
    archive = move(prices)   # explicit ownership transfer
    # print(prices)          # <- serp: error[SE001] use-after-move

if __name__ == "__main__":
    main()
```

Ownership is encoded exclusively through constructs CPython ignores at runtime: type
annotations, decorators, and the `serpentine-shim` package where `Owned`/`Ref`/`Mut`/`move`
are no-ops.

## Repository layout

| Path | What |
|---|---|
| `docs/` | All documentation — see [docs/README.md](docs/README.md) for the index |
| `docs/spec.md` | The language specification — the wall against scope creep |
| `docs/features.md` | Current feature state (language, compiler, tooling, libraries) |
| `docs/decisions.md` | Resolved design questions |
| `docs/libraries.md` | Library roadmap & tracker |
| `shim/` | `serpentine-shim` — the runtime no-op package (`pip install serpentine-shim`) |
| `compiler/` | `serpentine-lang` — the `serp` compiler & CLI |
| `libs/` | The `serp-*` library monorepo |
| `tests/accept/` | Programs the checker must accept; each runs under CPython today |
| `tests/reject/` | Programs the checker must reject; each annotated with its expected error |

## Version pin

The spec grammar and CI are pinned to **CPython 3.12**; the packages install on 3.11+ and the
local test suites also pass on 3.11. Raising the pin is a deliberate spec change, not an
incidental upgrade.

## License

MIT — see [LICENSE](LICENSE).
