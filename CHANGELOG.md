# Changelog

All notable changes to `serpentine-lang` (compiler) and `serpentine-shim`. Library releases
(`serp-*` / `serpentine-*` on PyPI) are tracked in [docs/libraries.md](docs/libraries.md).
Everything is `0.x`: the language surface, SE codes and runtime ABI may change between minor
versions.

## [Unreleased]

### Security / hardening
- Native crashes print a CPython-style traceback (`.py` file, line, function per frame) in
  both backends; frames are recorded on the error path only.
- `serp-re`: ReDoS guard of 1M VM steps and 10k recursion levels per match attempt; raises
  `serp_re.error` instead of hanging or overflowing the stack.
- `serp-zlib` / `serp-zipfile`: 256 MiB decompression-output cap (bomb guard).
- `serp-http-server` / Venom: request bodies over 16 MiB get `413 Payload Too Large` before
  being read.
- The program entry and all runtime threads run on 256 MiB reserved stacks, so Windows
  matches Linux/macOS recursion depth.
- New tooling (in CI unless noted): `run_traceback_check.py`, `run_fuzz.py` (differential
  parser fuzzer), `run_compiler_fuzz.py` (random-program differential fuzzer),
  `run_tls_check.py` (badssl.com; informational in CI), `run_miri.py`, `run_asan.py` and
  `run_soak.py` (local/nightly).

### Fixed (found by the fuzzers)
- `bytes.fromhex` ignored only spaces; it now ignores all ASCII whitespace, like CPython.
- `zlib.decompress` read the Adler-32 from the last 4 bytes; it now reads it right after the
  DEFLATE stream and ignores trailing data, like CPython.
- `gzip_decompress` now decodes concatenated members and skips NUL padding, like CPython.
- `str.strip`/`lstrip`/`rstrip`/`split()`, `int()` and `float()` now treat `\x1c`–`\x1f` as
  whitespace, like CPython. The TOML parser behaved differently natively on control
  characters because of this.

### Fixed
- Backend A: a local first assigned inside a `try` body and used after a diverging handler
  (`except: continue|break|return`) no longer fails rustc with E0381. Scalar and Optional locals
  assigned inside a `try` get a zero initializer.

### Added
- Accept 105 (`finally` runs exactly once around loops; handler `break`/`continue` with `finally`
  in `while` and nested loops) and 106 (try-assigned int/float/bool/Optional locals).

### Notes
- `return` inside a `try` with `finally` is rejected at compile time (SE201, reject r044) by
  design, as is `break`/`continue` out of a `try` *body*. Neither can silently skip a `finally`.

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
- Backend A: E0381 on locals assigned in `try` and used after `except: continue`. Fixed in Unreleased.

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
