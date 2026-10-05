# Serpentine Production-Readiness Checklist

> Whether the project as a whole is safe to depend on. [libraries.md](libraries.md) tracks library
> *features*; [CHANGELOG.md](../CHANGELOG.md) tracks what shipped in each release.
>
> `[ ]` open · `[~]` partial · `[x]` done. Priority: **P1** blocks production services with real
> users, **P2** is needed for broad adoption. Every done item names its evidence.
>
> Last assessed: **2026-10-05** (compiler 0.7.2 released; hardening on `master`, unreleased).

## Verdict

| Level | Meaning | Status |
|---|---|---|
| **L1 — Experimental** | Hobby projects, demos, benchmarks | ✅ Passed |
| **L2 — Internal tools** | CLIs, batch jobs, data scripts, internal services where a crash costs little | ✅ **Reached** (0.7.2) |
| **L3 — Production service** | Internet-facing, many users, on-call | ❌ Not yet. See *Remaining for L3* |

**Can I build on it today?** Yes, for L2 work. The compiler is byte-identical across CPython and
both native backends on Windows, Linux and macOS, and it's fuzzed, sanitizer-checked and soak-tested.
For an internet-facing service, the open items below are what's missing: mostly operations
(graceful shutdown, observability), ecosystem (databases, auth, timezones) and language reach
(no regular PyPI packages).

---

## Remaining for L3 (P1)

Ordered roughly by what unblocks a real service soonest.

### Release & process
- [ ] **Release 0.7.3.** The hardening pass, crash tracebacks and the Linux SIGPIPE fix are on `master` but not on PyPI yet.
- [ ] **Stability & versioning policy** for the language surface, SE codes and runtime ABI (everything is `0.x`).
- [ ] **Enable GitHub private vulnerability reporting** in the repo settings ([SECURITY.md](../SECURITY.md) already points to it).
- [ ] **Stabilize flaky lib tests:** `serp-fang/test_async_fang` fails under CPython on the Windows dev box (loopback `connection reset` in the pure-Python socket facade), and `serp-asyncio/test_asyncio` occasionally misorders under heavy parallel load. Both pass in isolation and in CI.

### Running services (Venom stack)
- [ ] **Graceful shutdown:** drain in-flight requests on SIGTERM/Ctrl-C (there's no signal handling today; a kill does release the port immediately).
- [ ] **Health endpoint** pattern and process-manager/container restart guide.
- [ ] **Per-request read deadline** (slowloris). The current 10 s timeout applies per `recv`.
- [ ] **24h+ soak on Linux server hardware** with latency-drift tracking (`tools/run_soak.py --seconds 86400`).
- [ ] **Re-benchmark on Linux**, with load generators on separate hosts.
- [ ] **Observability:** metrics (Prometheus) and tracing (OpenTelemetry) libraries; `serp-log` covers logging only.
- [ ] **Venom features:** middleware, `BackgroundTasks`, streaming responses, WebSockets, CORS ([libraries/venom.md](libraries/venom.md)).

### Ecosystem
- [ ] **Database clients:** PostgreSQL, MySQL, Redis.
- [ ] **SQLite transactions** (`serp-sqlite` is autocommit-only).
- [ ] **Timezones** in `serp-datetime` (`zoneinfo` / tz-aware datetimes).
- [ ] **Auth/crypto:** `hmac`, JWT, password hashing (bcrypt/argon2).

### Security & robustness
- [ ] **Sanitize Backend B:** ASan/UBSan over the LLVM-emitted objects (today ASan and Miri cover Backend A only).
- [ ] **Checker robustness fuzz:** `serp check` must never crash on arbitrary (ill-typed or garbage) input.
- [ ] **Fuzz HTTP request parsing** in http-server/Venom (limits are tested; the parser isn't fuzzed).
- [~] **`Shared` reference cycles** leak by design (D3). There's guidance in [language/ownership.md](language/ownership.md) §7.1, but no runtime detection.

### Language reach
- [ ] **Python interop:** D6 refuses foreign imports, so no regular PyPI package can be used; only `serp-*` libs ([guides/interop.md](guides/interop.md)).
- [ ] **General closures:** lambdas capture Copy values only; comprehensions allow one `for` + one `if`.
- [ ] **`int` is int64** with an overflow trap, not a bignum ([language/divergences.md](language/divergences.md)).
- [ ] **Imports:** only `from a.b import x`; plain `import a.b` and relative imports are refused.
- [ ] **Scale test:** compile time and memory on a 10k–50k LOC program (never measured past the libs).

## Remaining for broad adoption (P2)

- [ ] **Developer experience:** LSP completion, hover and go-to-definition, plus a VS Code extension (the LSP serves diagnostics only); an error-code reference page with examples (today only spec §12); an end-to-end "production web service" tutorial (Venom + Molt + deploy).
- [ ] **Debugging & profiling:** DWARF/PDB line mapping back to `.py` for gdb/lldb/VS; a profiling guide (perf/VTune/ETW).
- [ ] **Platforms:** linux-arm64, macos-x86_64 and musl/Alpine CI + prebuilt runtimes; a Codon comparison benchmark (needs a Linux host).
- [ ] **Compiler scale:** incremental/cached compilation for large projects; a diagnostics quality pass (every SE code has an example + fix).
- [ ] **Language:** subtype polymorphism / `super()` / virtual dispatch (out of scope by D15, so a migration-patterns doc is owed); returned borrows (SE209), `Sync[T]` and scoped cross-thread borrows; asyncio cancellation, `wait_for`, `async for`, `Task.result()` and multiple loops; `class Worker(Thread)` subclassing; a `Decimal` pattern (D26 rejected it).
- [ ] **Ecosystem:** templating, an ORM/query builder, a background job queue, cloud SDKs; `serp-molt` `plain`/`wrap` validators; typed Scales storage.
- [ ] **Services:** HTTP/2; a container image + deployment guide.
- [ ] **Governance:** `CONTRIBUTING.md`, issue/PR templates, a code of conduct, and onboarding docs for a second maintainer.
- [ ] **Local/CI parity:** the local venv is CPython 3.11, CI pins 3.12.
- [ ] **Public announcement** (venues in [guides/publishing.md](guides/publishing.md)).

---

## Done

**Source control, CI, releases**
- [x] Three-OS CI (ubuntu/macos/windows): accept/reject corpora, both backend differentials, rustc agreement, LSP smoke, every lib suite, tracebacks, parser + compiler fuzz smoke, TLS check.
- [x] `serpentine-lang` 0.7.2 + `serpentine-shim` 0.9.0 on PyPI via trusted publishing (`release.yml`); prebuilt runtimes for linux-x86_64, macos-arm64 and windows-x86_64 attached to each release.
- [x] All 37 `serp-*` libraries on PyPI (`release-lib.yml`; `serp-io`/`serp-cli` ship as `serpentine-io`/`serpentine-argparse`).
- [x] `CHANGELOG.md`, `SECURITY.md`, README CI/PyPI badges and an experimental-status warning.

**Language** ([features.md](features.md), [spec.md](spec.md))
- [x] Tier 0–2 static typing, ownership/borrowing, unions, enums, generics + protocols, `PyVal`.
- [x] Classes: dataclasses, `__init__`/`__post_init__`, operators, properties, classmethods, single inheritance (D15).
- [x] Exceptions, first-class functions, decorators (D13), kwargs, the iterator protocol.
- [x] Concurrency: `spawn`/`join` (D9), `serp-threading`, the asyncio baton runtime (D45).

**Compiler correctness** ([guides/testing.md](guides/testing.md))
- [x] Accept corpus 001–106 byte-identical across CPython, Backend A and Backend B (debug + release) on 3 OSes; reject corpus with exact SE codes; rustc agreement at 0 disagreements.
- [x] Silent miscompiles fixed with regression tests: the Backend-B `IfExp` temp drop (Molt `test_schema_repeat`); `break`/`continue` skipping `finally` (accept 104/105); Backend-A E0695/E0381 (accept 104/106). `return` through `finally` is rejected at compile time (SE201, r044).
- [x] Compiler differential fuzzer: random well-typed programs, identical across all three (30/30; 8 in CI).

**Runtime safety & security** ([language/divergences.md](language/divergences.md) §Safety limits)
- [x] Ownership rules out use-after-free and data races in user code (borrowck + rustc oracle); `serp add` verifies sha256 and `serp.lock` pins versions.
- [x] Parser fuzzing: JSON, TOML, URL, base64, regex, raw/zlib/gzip inflate, CSV. 72k cases, 0 crashes, 0 divergences after 4 real fixes (fixed-seed run in CI).
- [x] `unsafe` runtime checks: Miri clean on 19 FFI-free programs; AddressSanitizer clean on all 101 single-file accept programs (Backend A).
- [x] Limits: regex 1M steps / 10k depth (ReDoS), 256 MiB decompression cap, 16 MiB HTTP body cap (413), 64 KiB HTTP heads, 256 MiB stacks for every thread.
- [x] TLS: expired, self-signed, wrong-host and untrusted-root certificates refused on Windows, Linux and macOS (`tools/run_tls_check.py`, 6/6 each).
- [x] Zero third-party Rust crates in the runtime (OS TLS + system SQLite only).

**Running services**
- [x] Venom 0.4.0: `fastapi` drop-in with threaded keep-alive, event-loop and async servers; axum parity (1.05–1.06x at w1/c16, 0.92–1.03x at w3/c64, one Windows box).
- [x] Crash tracebacks: uncaught native errors print `.py` file/line/function per frame, matching CPython (`tools/run_traceback_check.py`).
- [x] 10-minute soak: 10.4M requests, RSS and handle count flat after warm-up; the port is released immediately on kill.
- [x] Linux/macOS binaries ignore SIGPIPE (a peer closing an HTTPS connection used to kill the process).
