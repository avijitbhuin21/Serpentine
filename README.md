# Serpentine

> Python source code, written under an ownership-and-borrowing discipline, ahead-of-time
> compiled to native machine code with **no garbage collector** — while the exact same file
> remains valid, runnable CPython. One codebase, two execution modes.

**Status:** v0.5 — full compiler shipped: LLVM-direct native builds (default backend) with a
rustc oracle pass on release builds, project tooling (`serp init` / `add` / `run`), packages,
LSP, and a 59-program dual-run corpus, byte-identical on Windows/Linux/macOS.

## Quick start

```console
pip install serpentine-lang        # brings uv + the shim along
serp new myapp --git               # scaffold: serp.toml, main.py, .venv (shim installed), git
cd myapp
serp run                           # build (LLVM, debug) + run
serp build main.py                 # native binary (release: O3 + runtime LTO + rustc oracle)
serp add somelib                   # add a Serpentine library from PyPI (pinned in serp.lock)
```

`serp check` gives ownership/type diagnostics; `serp lsp` serves them to your editor.

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

The spec grammar and CI are pinned to **CPython 3.12**. Raising the pin is a deliberate spec
change, not an incidental upgrade.

## License

MIT — see [LICENSE](LICENSE).
