# Changelog

All notable changes to `serpentine-lang` (compiler) and `serpentine-shim`. Library releases
(`serp-*` / `serpentine-*` on PyPI) are tracked in [docs/libraries.md](docs/libraries.md).
Everything is `0.x`: the language surface, SE codes and runtime ABI may change between minor
versions.

## [Unreleased]

## [0.7.2] — 2026-09-30

### Fixed
- `break`/`continue` leaving a `try` now run the pending `finally` bodies (innermost first) in
  both backends. Before this, the `finally` was skipped silently.
- Backend A: a bare `continue`/`break` inside a `try` or `except` within a loop no longer fails
  rustc with E0695. Loops that need it now get a label (`'lpN:`).

### Added
- Accept 103 (non-Copy `str` ternary with a call arm) and 104 (`continue`/`break` inside
  `except`, with `finally`, nested loops).
- `serp-molt` `test_schema_repeat`: a regression guard for the Backend-B `IfExp` temp-drop crash
  (fixed 2026-08-30). It crashes a pre-fix compiler on every run.

### Known issues
- Backend A: `try: x = f()` / `except: continue` followed by a use of `x` fails rustc with E0381
  (possibly-uninitialized). Workaround: initialise `x` before the `try`.

## [0.7.1] — 2026-09-29
- Dependency import roots are resolved from `*.dist-info` metadata, so dists whose names differ
  from their import names (`serpentine-io` → `serp_io`, `serpentine-argparse` → `serp_cli`) can be imported.
- `serp add` accepts `serpentine_*` dependencies as Serpentine libraries.

## [0.7.0] — 2026-09-28 (shim 0.9.0)
- Phase 7 waves 5–6: compiler features D13–D45: decorators, eager async + asyncio baton
  runtime, threads (D9 v1/v2), single inheritance, iterator protocol, `__repr__`/`__post_init__`,
  exception `__init__`, module-level object bindings + `@registrar` decorators, union
  narrowing, tuple/slice keys, PyVal dict keys and more.
- These enabled the Molt (pydantic), Coil (numpy), Scales (pandas), Venom (FastAPI), threading,
  queue, asyncio and subprocess libraries.
- Shim: `__init_subclass__` forwarding for CPython 3.12 `Generic`.
- Unix TLS buffering helper (`SSL_pending`); runtime asset naming follows `__version__`.
- Accept corpus 070–102, reject corpus r053–r095.

## [0.6.0] — 2026-07-23
- Phase 7 start: stdlib drop-in libraries and the language features they needed (kwargs,
  dataclass defaults, `__str__`, `@property`/`@staticmethod`, `with` on objects, PyVal dynamic
  values, user exceptions, first-class functions, operator overloading, bytes/bytearray).

## [0.5.0] — 2026-07-21
- Phase 5: full-language direct-to-LLVM backend (Backend B), now the default. Release builds add
  a rustc oracle pass.
- Phase 6: project tooling: packages, `serp init/new/run/add/remove`, `serp.toml` + `serp.lock`,
  prebuilt runtime distribution.

## [0.4.0] — 2026-07-20
- First PyPI release (`serpentine-lang` + `serpentine-shim` 0.3.0) via trusted publishing.
- Element borrows, field-place narrowing, `iter()`/`next()`, `Owned` self, SSO string runtime,
  multi-package design, LSP smoke test in CI.
