# Serpentine Production-Readiness Checklist

> Whether the project as a whole is safe to depend on. [libraries.md](libraries.md) tracks library
> _features_; [CHANGELOG.md](../CHANGELOG.md) tracks what shipped in each release.
>
> `[ ]` open · `[~]` partial · `[x]` done. Priority: **P1** blocks production services with real
> users, **P2** is needed for broad adoption. Every done item names its evidence.
>
> Last assessed: **2026-10-27** (compiler 0.7.3 prepared, unreleased; L3 pass on `master`).

## Verdict

| Level                       | Meaning                                                                      | Status                             |
| --------------------------- | ---------------------------------------------------------------------------- | ---------------------------------- |
| **L1 — Experimental**       | Hobby projects, demos, benchmarks                                            | ✅ Passed                          |
| **L2 — Internal tools**     | CLIs, batch jobs, data scripts, internal services where a crash costs little | ✅ **Reached** (0.7.2)             |
| **L3 — Production service** | Internet-facing, many users, on-call                                         | ❌ Not yet. See _Remaining for L3_ |

**Can I build on it today?** Yes, for L2 work. The compiler is byte-identical across CPython and
both native backends on Windows, Linux and macOS, and it's fuzzed, sanitizer-checked and soak-tested.
For an internet-facing service, the open items below are what's missing. Operations basics
(graceful shutdown, health checks, slowloris guard, metrics, tracing, HTTP fuzzing), Venom
middleware/CORS/background tasks/streaming and auth/crypto are now in place. What remains is
mostly infrastructure-bound verification (24h Linux soak, multi-host Linux benchmarks),
ecosystem breadth (PostgreSQL/MySQL, `zoneinfo`, WebSockets) and language reach (no regular
PyPI packages, int64, non-Copy closure captures).

---

## Remaining for L3 (P1)

Ordered roughly by what unblocks a real service soonest. Items closed in the 2026-10-27 pass
keep their line here with the evidence, so the gap to L3 stays readable in one place.

### Release & process

- [~] **Release 0.7.3.** Prepared (version bump, CHANGELOG `[0.7.3]`) but not tagged/published; publishing to PyPI is irreversible and waits for the maintainer. The prebuilt `dist-rt` runtime needs refreshing (prelude.rs/rt.rs changed).
- [x] **Stability & versioning policy**: [stability.md](stability.md) (SemVer rules for `0.x`, per-surface guarantees for programs, SE codes, CLI, `serp.toml`, runtime ABI, shim and libraries; deprecation; road to 1.0).
- [ ] **Enable GitHub private vulnerability reporting.** Blocked: GitHub only offers it on public repositories and the repo is private (`gh api … private-vulnerability-reporting` → 404). Enable it when the repo goes public.
- [x] **Stabilize flaky lib tests:** `test_async_fang`: the test server closed with an unread POST body, so Windows sent RST and the response was lost (1/5 → 20/20 under CPython). `test_asyncio`: equal-deadline sleeps and 10 ms margins (now 32/32 per backend at 8 concurrent runs).

### Running services (Venom stack)

- [x] **Graceful shutdown:** SIGTERM/SIGINT/Ctrl-C/Ctrl-Break → stop accepting, drain in-flight requests (`SHUTDOWN_GRACE` 10 s), close idle keep-alives, exit 0; a second signal exits immediately. `tools/run_shutdown_check.py`: 4/4 (both backends × `serve_async`/`serve_on`, real signals) on Windows; Unix handler type-checked for linux-gnu. `test_shutdown.py` byte-identical in all three worlds.
- [x] **Health endpoint pattern and restart guide**: [guides/deployment.md](guides/deployment.md) (liveness/readiness routes, systemd, Docker, Kubernetes probes, stop timeouts, scaling).
- [x] **Per-request read deadline** (slowloris): whole-request budget `REQUEST_DEADLINE` (30 s, head + body) on top of the 10 s per-`recv` timeout, in http-server, threaded Venom and the event loop (`test_shutdown.py` drops a trickling request).
- [ ] **24h+ soak on Linux server hardware** with latency-drift tracking (`tools/run_soak.py --seconds 86400`). Needs a Linux host; not available from the Windows dev box.
- [ ] **Re-benchmark on Linux**, with load generators on separate hosts. Needs Linux hosts.
- [x] **Observability:** metrics: `serp-prometheus` (Counter/Gauge/Histogram/Summary, labels, text exposition, process-global store shared by worker threads). Tracing: `serp-tracing` (OpenTelemetry-style nested spans, attributes/events/status, W3C `traceparent` inject/extract for cross-service traces, memory/stderr/file JSON exporters). No OTLP network exporter yet.
- [~] **Venom features:** done in Venom 0.5.0: `@app.middleware("http")` chains (FastAPI spelling, latest-added outermost, wraps 404/405 and handler errors), `app.add_middleware(CORSMiddleware, ...)` with Starlette semantics, `BackgroundTasks` (injected; run after the response is written; `add_task` takes a zero-arg callable), `StreamingResponse` (chunked transfer encoding) and `LazyStreamingResponse(producer)` (chunks computed while the response is written; the producer may capture non-Copy data). `test_middleware.py`/`test_streaming.py` identical in all three worlds. Still open: WebSockets, generator-function syntax for streaming (`yield`, LB8), async `def` middleware.

### Ecosystem

- [~] **Database clients:** `serp-redis` (redis-py-style RESP2; verified against a scripted RESP server, wire bytes checked; not yet run against a live Redis). PostgreSQL and MySQL are still open (no live server to verify their auth handshakes here).
- [x] **SQLite transactions**: sqlite3 legacy rules (implicit `BEGIN` before DML, `commit`/`rollback`, `in_transaction`, `isolation_level` incl. `None` and `IMMEDIATE`, savepoints); `test_transactions.py` identical in all three worlds.
- [~] **Timezones** in `serp-datetime`: fixed-offset `timezone`/`timezone.utc`/`UTC`, aware datetimes (`astimezone`, `timestamp`, `now(tz)`, `fromtimestamp(ts, tz)`, aware comparisons, ISO offsets), all byte-identical to CPython (`test_timezone.py`). IANA `zoneinfo` (DST rules) is still open.
- [x] **Auth/crypto:** `serp-hmac` (hmac drop-in, RFC 4231 vectors), `hashlib.pbkdf2_hmac` (RFC 6070), `serp-jwt` (HS256 token byte-identical to PyJWT's README vector, exp/nbf/iat/aud/iss), `serp-bcrypt` (0 mismatches vs pyca/bcrypt 4.0.1 incl. 2a/2b and >72-byte passwords). HMAC/PBKDF2/bcrypt run natively in the runtime.

### Security & robustness

- [x] **Sanitize Backend B:** `tools/run_asan.py --backend llvm` builds Backend B's runtime and stub with AddressSanitizer (`SERP_RUSTC_FLAGS` now reaches llvmbuild): 101/101 single-file accept programs clean. llvmlite can't instrument the emitted program IR, so this covers the runtime (all `unsafe` code); the program IR is safe Rust-equivalent code checked by the borrow checker.
- [x] **Checker robustness fuzz:** `tools/run_check_fuzz.py` mutates the accept/reject corpora and garbage; 41,500 cases over 3 seeds, 0 crashes (every input yields diagnostics or a clean check).
- [x] **Fuzz HTTP request parsing:** `tools/run_http_fuzz.py` found 3 server-killing bugs (malformed percent-encoding, 20-digit Content-Length overflow, peer reset mid-send). All fixed; now 4/4 runs × 3,000 cases (both backends × both serve modes), 0 malformed replies, server alive.
- [~] **`Shared` reference cycles** leak by design (D3). There's guidance in [language/ownership.md](language/ownership.md) §7.1, but no runtime detection.

### Language reach

- [ ] **Python interop:** D6 refuses foreign imports, so no regular PyPI package can be used; only `serp-*` libs ([guides/interop.md](guides/interop.md)).
- [x] **General closures:** lambdas capture **non-Copy values** (lists, dicts, dataclasses): the capture is a clone, and the checker makes that indistinguishable from CPython's by-reference closure by rejecting any mutation, move or rebinding of the captured variable after capture (SE004), any mutation or move of it inside the lambda (SE004), and non-Copy captures in a lambda built inside a loop (SE005). Accept 111 is identical in all three worlds; r096–r098 prove each rule. Lambdas may return `None` (accept 109; fixed a Backend-B path that dropped such bodies), and comprehensions take any number of `for`/`if` clauses (accept 110). Remaining by design: mutable shared closure state (use `Shared[T]`).
- [~] **`int` is int64** with an overflow trap, not a bignum ([language/divergences.md](language/divergences.md)). Arbitrary precision is available as `serp-bigint` (`BigInt` with `+ - * // % **`, `abs`, comparisons, divmod; 0 mismatches against CPython `int` on 37,854 randomized checks; dual-run identical natively; `abs()` now dispatches to `__abs__`). Making the built-in `int` unbounded was investigated and deferred: it's a Copy `i64` behind ~1,580 references (llvmgen 612, prelude.rs 518, rt.rs 369, rustgen 40, typecheck 41) covering every arithmetic, hash, format, FFI and PyVal path. That's a spec decision plus a rewrite of both backends' integer codegen.
- [x] **Imports:** plain `import a.b` / `import a.b as c` (accept 108). Relative imports are still refused by design (full dotted paths from the project root).
- [x] **Scale test:** `tools/run_scale_test.py`. 10.5k LOC: check 1.8 s, Backend A build 28 s, Backend B 51 s. 52k LOC / 75 modules: check 9.1 s (199 MiB), Backend A build 200 s (250 MiB compiler; 19 MiB binary), Backend B build 385 s (**2.1 GiB** compiler peak: llvmlite codegen runs in-process; 8 MiB binary). Output matches CPython in both. Backend B memory at this size and incremental builds are P2 follow-ups.

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
