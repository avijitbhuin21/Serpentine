# Changelog

All notable changes to `serpentine-lang` (compiler) and `serpentine-shim`. Library releases
(`serp-*` / `serpentine-*` on PyPI) are tracked in [docs/libraries.md](docs/libraries.md).
Everything is `0.x`: the language surface, SE codes and runtime ABI may change between minor
versions.

## [0.7.4] — 2026-10-27

Public-launch readiness release (compiler 0.7.4, shim 0.9.2, serp-scales 0.2.1).

### Fixed
- `pip install serpentine-lang` now pulls in `llvmlite`. Before, the default LLVM backend crashed
  with a Python traceback (`serp run` / `serp build`) unless the `[llvm]` extra was installed. The
  extra remains as an alias, and a missing `llvmlite` now prints a clear message instead.
- f-string format specs: `serp check` accepted specs such as `{n:03d}`, `{x:>10.2f}`, `{n:,}`,
  `{n:#x}` or `{x:.1%}` that native builds then failed on with an internal codegen error. Both
  backends now implement CPython's format mini-language for `int`, `float`, `bool` and `str` (fill,
  alignment incl. `=`, sign, `#`, zero-padding, width, `,`/`_` grouping, precision and the
  `b c d o x X n e E f F g G %` types), matched against CPython on a 92-line matrix (accept 112)
  and 720 random specs. The checker validates every spec at compile time and rejects specs CPython
  would refuse (r100, r101), dynamic `{x:{w}}` specs (r099) and the few unimplemented forms (`z`,
  `#` on floats, zero-padding together with a separator).
- A plain `import requests` (or any unresolvable module) is now SE213 even when no member is used
  (r102); before, an unused foreign import passed `serp check`.
- serp-scales 0.2.1 pins serp-datetime 0.4.0 (it pinned 0.2.0, which conflicted with serp-molt).
- `serpentine.__version__` reported 0.8.0; it now matches the package (0.9.2).

### Improved
- Diagnostics carry `help:` lines with the fix for the most common newcomer errors: generator
  expressions, `*args`/`**kwargs`, plain classes/`super()`, module-level script code, the walrus
  operator, and foreign imports (with the matching `serp-*` library, e.g. `os` -> `serp add serp-os`).
  "Tier-0" jargon is gone from messages, and long SE213 search paths are shortened.
- Missing-`rustc` messages link to rustup.rs. Typographic dashes fall back to ASCII when output is
  piped through a non-UTF-8 console.
- README: requirements, a "what compiles / what doesn't" table, corrected status and benchmark
  framing; the compiler's PyPI page is rewritten; PyPI classifiers and project URLs added.
- Governance: CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue and pull-request templates.

## [0.7.3] — 2026-10-27

Released alongside: serpentine-shim 0.9.1; serp-datetime 0.4.0, serp-sqlite 0.3.0,
serp-hashlib 0.2.0, serp-http-server 0.2.0, serp-socket 0.2.0, serp-url 0.1.1, serp-venom 0.5.0,
serp-log 0.2.1, serp-molt 0.7.1, serp-re 0.2.1 (ReDoS step/depth limits), serp-zlib 0.1.1
(256 MiB decompression cap, fuzz fixes); new: serp-hmac, serp-jwt, serp-bcrypt, serp-prometheus,
serp-redis, serp-tracing, serp-bigint 0.1.0. The compiler now requires serpentine-shim>=0.9.1.

### Language / compiler
- Lambdas capture non-Copy values (cloned into the closure); soundness rules keep this equal
  to CPython's by-reference capture: no mutation/move/rebinding after capture, no mutation/move
  inside the lambda, no non-Copy capture in a lambda built inside a loop (accept 111;
  r096–r098). Fixed: rustgen moved non-Copy captures into the closure instead of cloning.
- `abs(x)` on a class dispatches to `__abs__` (new allowed dunder).
- Lambdas may return `None` (callbacks such as `add_task(lambda: f(x))`); Backend B used to drop
  such bodies (`return <expr>` in a `None` function never evaluated), Backend A rejected
  `print(...)` bodies — both fixed (accept 109).
- Comprehensions take any number of `for`/`if` clauses: extra `if`s merge into `and`, extra
  `for`s lower to a nested comprehension + generic `_serp_flatten` (CPython element and
  evaluation order; set comprehensions go through `set()`; dict ones still take one `for`)
  (accept 110; r029 now targets multi-`for` dict comprehensions).
- D41 registrars whose endpoint is a 2-argument callable (`@app.middleware("http")`) receive the
  decorated function itself; a bare `request: Request, call_next` signature is completed from the
  registrar and `call_next(request)` gets an explicit move.
- D41 handler injection: a `BackgroundTasks` parameter is created per request, passed `Mut`, and
  its tasks are moved onto the returned `Response`.
- Plain `import a.b` and `import a.b as c`: `a.b.name` / `c.name` resolve like
  `from a.b import name` (functions, classes in annotations, constants, runtime-library
  members). `import serpentine/typing/enum` stays `from`-only (accept 108).
- Class attributes bound at module level: `C.attr = D(...)` after `class C` becomes a
  build-time factory (D41 extension), so `timezone.utc`-style constants work across modules
  (accept 107).
- Fixed: rustgen dropped the unwrap on a narrowed Optional *field* used as a base
  (`self.tz.offset`, `self.a.b.c`) → rustc E0609 (accept 107).
- Fixed: Backend B printed an `Optional[C]`/union member with `__repr__` instead of `__str__`.
- Fixed: rustgen crashed on a `bytes` parameter default (`prefix: bytes = b"2b"`).
- Runtime: `accept_nb` always returns a blocking socket (Windows inherited the listener's
  non-blocking mode).
- `SERP_RUSTC_FLAGS` now also reaches Backend B's runtime build and final link (and the
  runtime cache key), so the runtime can be built with AddressSanitizer.
- Fixed: on the Microsoft Store Python, a fresh Backend B runtime build failed with
  "couldn't find file …serp_rt.rs" (the Store sandbox hides `%LOCALAPPDATA%` writes from
  rustc); the temp-dir fallback now covers this error too.

### Services (Venom 0.5.0 / serp-http-server 0.2.0)
- `@app.middleware("http")` middleware chains (FastAPI spelling; latest-added outermost; wraps
  404/405 and converted handler exceptions), `app.add_middleware(CORSMiddleware, ...)` with
  Starlette's preflight/simple-request rules, `BackgroundTasks` (run after the response is
  written, in every server and in `TestClient`), `StreamingResponse` (chunked transfer
  encoding). Fixed (CPython only): response factories shared their mutable `headers={}` default,
  so headers leaked between responses.
- Graceful shutdown: `shutdown_install()` (called by `run()`) routes SIGTERM/SIGINT/Ctrl-C/
  Ctrl-Break to a flag; `serve_async` and `serve_on` stop accepting, drain in-flight requests
  (`SHUTDOWN_GRACE` 10 s), close idle keep-alive connections and return; a second signal
  exits at once. `shutdown_request()`/`shutdown_requested()` for code.
- Slowloris guard: whole-request read deadline (`REQUEST_DEADLINE` 30 s, head + body) on top
  of the 10 s per-`recv` timeout; `serve_async(..., read_deadline=)`.
- Crash containment found by the new HTTP fuzzer: malformed percent-encoding, a 20-digit
  `Content-Length` and a peer reset mid-send each killed the server; they now yield
  500/413/close for that connection only.
- `serp-url`: `unquote` decodes invalid UTF-8 with CPython's `errors='replace'` semantics
  (200k-case parity).

### New libraries
- `serp-bigint` (arbitrary-precision `BigInt`, CPython-exact floor semantics).
- Venom `LazyStreamingResponse(producer)`: chunks produced while the response is written.
- `serp-tracing` (OpenTelemetry-style spans, W3C `traceparent` inject/extract, memory/stderr/file
  JSON exporters).
- `serpentine-shim` 0.9.1: `registrar` passes 2-argument callables (middleware) through and injects
  `BackgroundTasks`.
- `serp-hmac` (hmac drop-in), `serp-jwt` (PyJWT-compatible HS256 with exp/nbf/iat/aud/iss),
  `serp-bcrypt` (pyca/bcrypt-compatible, byte-identical hashes), `serp-prometheus`
  (prometheus_client-style metrics + text exposition), `serp-redis` (redis-py-style RESP2).
- `serp-hashlib` 0.2.0: `pbkdf2_hmac`; native HMAC/PBKDF2/bcrypt/constant-time compare in the
  runtime.
- `serp-datetime`: fixed-offset `timezone` (`timezone.utc`, `UTC`), aware datetimes
  (`tzinfo=`, `utcoffset/tzname/astimezone/timestamp`, `now(tz)`, `fromtimestamp(ts, tz)`,
  `replace`, aware comparisons/arithmetic, `fromisoformat` offsets and `Z`).
- `serp-sqlite`: transactions with sqlite3's legacy rules (implicit `BEGIN` before DML,
  `commit`/`rollback`, `in_transaction`, `isolation_level`).

### Tooling
- `run_shutdown_check.py` (real-signal drain, both backends × both serve modes),
  `run_http_fuzz.py`, `run_check_fuzz.py` (checker never crashes), `run_scale_test.py`
  (10k–50k LOC), `run_asan.py --backend llvm`.
- Flaky tests fixed: `test_async_fang` (test server closed with unread body → Windows RST),
  `test_asyncio` (equal-deadline sleeps and tight margins).

### Docs
- `docs/stability.md` (versioning policy), `docs/guides/deployment.md` (health checks,
  shutdown, systemd/Docker/Kubernetes).

### Security / hardening (since 0.7.2)
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

### Fixed (found by the TLS check in CI)
- Linux/macOS LLVM builds link with a C `main` that bypassed Rust's start-up, so SIGPIPE was
  never ignored. Any HTTPS request whose peer closed first **killed the process with signal 13**
  on Linux (badssl check: 0/6). The C `main` now goes through `rt_main_trampoline`, which
  ignores SIGPIPE and runs the program on the same 256 MiB entry thread as on Windows.

### Fixed (found by the fuzzers)
- `bytes.fromhex` ignored only spaces; it now ignores all ASCII whitespace, like CPython.
- `zlib.decompress` read the Adler-32 from the last 4 bytes; it now reads it right after the
  DEFLATE stream and ignores trailing data, like CPython.
- `gzip_decompress` now decodes concatenated members and skips NUL padding, like CPython.
- `str.strip`/`lstrip`/`rstrip`/`split()`, `int()` and `float()` now treat `\x1c`–`\x1f` as
  whitespace, like CPython. The TOML parser behaved differently natively on control
  characters because of this.

### Fixed
- Packaging (found by installing every built wheel into a clean venv): the `serp-socket` wheel
  omitted `_serp_socket` and the `serp-log` wheel omitted `serp_log_core`, so CPython imports
  of those libs (and of serp-http-server/Fang/Venom through them) failed after `pip install`.
  Fixed in serp-socket 0.2.0 and serp-log 0.2.1.
- `serp-molt` 0.7.1: `datetime` fields stopped parsing from ISO text after serp-datetime 0.4.0
  added `tzinfo` (molt matched the 7-field layout only). Molt now requires serp-datetime>=0.4.0.
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
- Backend A: E0381 on locals assigned in `try` and used after `except: continue`. Fixed in 0.7.3.

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
